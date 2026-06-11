"""
后台工作线程 - 处理耗时操作
"""
from typing import Dict, Callable, Optional, Any, List, Sequence
import threading
import fitz
import re
import uuid
from pathlib import Path
from config import PDF_COMPRESSION, SKIP_KEYWORD


def normalize_text(text: Optional[str]) -> str:
    """规范化文本"""
    return re.sub(r"\s+", "", text or "")


def parse_feature_keywords(text: Optional[str]) -> List[str]:
    """解析特性筛选关键词，支持分号和换行分隔。"""
    parts = re.split(r"[;；\r\n]+", text or "")
    return [normalize_text(part) for part in parts if normalize_text(part)]


def page_matches_keywords(page: fitz.Page, keywords: Sequence[str]) -> bool:
    """判断页面文本是否包含任一特性关键词。"""
    if not keywords:
        return True
    page_text = normalize_text(page.get_text("text"))
    return any(keyword in page_text for keyword in keywords)


def save_pdf_atomic(doc: fitz.Document, output_pdf: str) -> None:
    """原子保存 PDF，避免失败时留下半写入文件。"""
    out_path = Path(output_pdf)
    temp_path = out_path.with_name(
        f".{out_path.stem}.{uuid.uuid4().hex}.tmp{out_path.suffix}"
    )
    if temp_path.exists():
        temp_path.unlink()

    try:
        doc.save(
            str(temp_path),
            garbage=PDF_COMPRESSION["garbage"],
            deflate=PDF_COMPRESSION["deflate"],
        )
        temp_path.replace(out_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def save_filtered_document(
    source: fitz.Document,
    output_pdf: str,
    keywords: Sequence[str],
    on_progress: Optional[Callable] = None,
    stop_event: Optional[threading.Event] = None,
    inverse: bool = False,
) -> Dict[str, Any]:
    """保存按特性关键词筛选后的新 PDF。"""
    progress = on_progress or (lambda *args: None)
    out = fitz.open()
    kept_pages = []
    total_pages = len(source)

    try:
        for index in range(total_pages):
            if stop_event and stop_event.is_set():
                raise InterruptedError("操作已被用户中断")

            page_number = index + 1
            has_keyword = page_matches_keywords(source[index], keywords)
            should_keep = not has_keyword if inverse else has_keyword
            if should_keep:
                out.insert_pdf(source, from_page=index, to_page=index)
                kept_pages.append(page_number)

            progress(
                page_number,
                total_pages,
                f"正在解析特性信息：第 {page_number} / {total_pages} 页",
            )

        if not kept_pages:
            keyword_text = "；".join(keywords)
            mode_text = "不包含" if inverse else "包含"
            raise ValueError(f"没有页面{mode_text}特性信息：{keyword_text}")

        progress(total_pages, total_pages, "正在保存筛选后的 PDF...")
        save_pdf_atomic(out, output_pdf)
        return {
            "matched_count": len(kept_pages),
            "removed_count": total_pages - len(kept_pages),
            "matched_pages": kept_pages,
            "feature_keywords": list(keywords),
            "filter_inverse": inverse,
        }
    finally:
        try:
            out.close()
        except Exception:
            pass


class FilterPDFWorker(threading.Thread):
    """PDF特性信息筛选工作线程"""

    def __init__(
        self,
        input_pdf: str,
        output_pdf: str,
        feature_keywords: str,
        filter_inverse: bool = False,
        on_progress: Optional[Callable] = None,
        on_complete: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
    ) -> None:
        super().__init__(daemon=False)
        self.input_pdf = input_pdf
        self.output_pdf = output_pdf
        self.keywords = parse_feature_keywords(feature_keywords)
        self.filter_inverse = filter_inverse
        self.on_progress = on_progress or (lambda *args: None)
        self.on_complete = on_complete or (lambda *args: None)
        self.on_error = on_error or (lambda *args: None)
        self._stop_event = threading.Event()
        self.result = None
        self.error = None

    def run(self) -> None:
        source = None
        try:
            if not self.keywords:
                raise ValueError("请输入要保留的特性信息")

            source = fitz.open(self.input_pdf)
            if len(source) == 0:
                raise ValueError("PDF 没有页面")

            self.on_progress(0, len(source), f"开始解析特性信息，共 {len(source)} 页")
            filter_result = save_filtered_document(
                source,
                self.output_pdf,
                self.keywords,
                on_progress=self.on_progress,
                stop_event=self._stop_event,
                inverse=self.filter_inverse,
            )
            self.result = {
                "success": True,
                "input_path": self.input_pdf,
                "output_path": self.output_pdf,
                "total_pages": len(source),
                **filter_result,
            }
            self.on_complete(self.result)
        except Exception as e:
            self.error = str(e)
            self.on_error(self.error)
        finally:
            if source:
                try:
                    source.close()
                except Exception:
                    pass

    def stop(self) -> None:
        """请求停止线程"""
        self._stop_event.set()

    def is_running(self) -> bool:
        """检查线程是否运行中"""
        return self.is_alive()


class MergePDFWorker(threading.Thread):
    """PDF合并工作线程
    
    在后台线程中执行PDF合并，避免UI卡顿
    通过回调函数向主线程报告进度
    """

    def __init__(self, base_pdf: str, barcode_pdf: str, output_pdf: str, params: Dict[str, float],
                 on_progress: Optional[Callable] = None, on_complete: Optional[Callable] = None,
                 on_error: Optional[Callable] = None, skip_keyword: Optional[str] = None,
                 reverse_save: bool = False, feature_filter_keywords: Optional[str] = None,
                 feature_filter_inverse: bool = False) -> None:
        """初始化工作线程
        
        Args:
            base_pdf: 基础PDF路径
            barcode_pdf: 条形码PDF路径
            output_pdf: 输出PDF路径
            params: 合并参数字典
            on_progress: 进度回调 (current, total, message)
            on_complete: 完成回调 (result)
            on_error: 错误回调 (error_message)
            skip_keyword: 跳过关键词 (如果为None则使用默认配置)
            reverse_save: 是否按相反页序保存输出
            feature_filter_keywords: 合并后只保留包含这些特性信息的页面
            feature_filter_inverse: 是否反选，保留不包含特性信息的页面
        """
        super().__init__(daemon=False)
        
        self.base_pdf = base_pdf
        self.barcode_pdf = barcode_pdf
        self.output_pdf = output_pdf
        self.params = params
        self.on_progress = on_progress or (lambda *args: None)
        self.on_complete = on_complete or (lambda *args: None)
        self.on_error = on_error or (lambda *args: None)
        self.skip_keyword = SKIP_KEYWORD if skip_keyword is None else skip_keyword
        self.reverse_save = reverse_save
        self.feature_filter_keywords = parse_feature_keywords(feature_filter_keywords)
        self.feature_filter_inverse = feature_filter_inverse
        
        self._stop_event = threading.Event()
        self.result = None
        self.error = None

    def run(self) -> None:
        """线程主函数"""
        try:
            self.result = self._merge_pdf()
            self.on_complete(self.result)
        except Exception as e:
            self.error = str(e)
            self.on_error(self.error)

    def _merge_pdf(self) -> Dict[str, Any]:
        """执行PDF合并
        
        Returns:
            dict: 合并结果统计
        """
        base = None
        barcodes = None
        out = None

        try:
            base = fitz.open(self.base_pdf)
            barcodes = fitz.open(self.barcode_pdf)
            out = fitz.open()

            total_barcode_pages = len(barcodes)
            self.on_progress(0, total_barcode_pages, f"开始处理，共 {total_barcode_pages} 页")

            skip_keyword_normalized = normalize_text(self.skip_keyword)
            valid_indices = []
            removed_pages = []
            for i in range(total_barcode_pages):
                page_text = barcodes[i].get_text("text")
                if skip_keyword_normalized and skip_keyword_normalized in normalize_text(page_text):
                    removed_pages.append(i + 1)
                else:
                    valid_indices.append(i)

            if len(base) == 0:
                raise ValueError("底板 PDF 没有页面")
            if len(barcodes) == 0:
                raise ValueError("条码 PDF 没有页面")
            if not valid_indices:
                raise ValueError("没有找到可合并的条码页面")
            allowed_base_page_counts = {1, total_barcode_pages, len(valid_indices)}
            if len(base) not in allowed_base_page_counts:
                raise ValueError(
                    "底板 PDF 页数必须为 1 页（作为通用模板），"
                    f"或与条码 PDF 总页数一致（{total_barcode_pages} 页），"
                    f"或与未跳过的条码页数一致（{len(valid_indices)} 页）。"
                    f"当前底板 PDF 页数：{len(base)} 页。"
                )

            valid_index_set = set(valid_indices)
            merge_jobs = []
            for i in range(total_barcode_pages):
                if i not in valid_index_set:
                    continue

                if len(base) == 1:
                    base_page_index = 0
                elif len(base) == total_barcode_pages:
                    base_page_index = i
                else:
                    base_page_index = len(merge_jobs)
                merge_jobs.append((i, base_page_index))

            removed_count = total_barcode_pages - len(merge_jobs)
            merged_count = 0
            if removed_count:
                self.on_progress(
                    0,
                    total_barcode_pages,
                    f"已跳过 {removed_count} 页：{removed_pages}",
                )
            output_jobs = list(reversed(merge_jobs)) if self.reverse_save else merge_jobs

            for output_index, (i, base_page_index) in enumerate(output_jobs, start=1):
                # 检查停止标志
                if self._stop_event.is_set():
                    raise InterruptedError("操作已被用户中断")

                page_number = i + 1
                barcode_page = barcodes[i]

                # 执行合并
                out.insert_pdf(base, from_page=base_page_index, to_page=base_page_index)
                page = out[-1]
                target_rect = self._calculate_rect(page, barcode_page)
                page.show_pdf_page(target_rect, barcodes, i)
                merged_count += 1

                self.on_progress(
                    output_index,
                    len(output_jobs),
                    f"正在合并：条码第 {page_number} 页 + 底板第 {base_page_index + 1} 页"
                    f"（输出第 {output_index} / {len(output_jobs)} 页）",
                )

            # 保存输出
            filter_result = None
            if self.feature_filter_keywords:
                self.on_progress(
                    total_barcode_pages,
                    total_barcode_pages,
                    "正在按特性信息筛选合并结果...",
                )
                filter_result = save_filtered_document(
                    out,
                    self.output_pdf,
                    self.feature_filter_keywords,
                    on_progress=self.on_progress,
                    stop_event=self._stop_event,
                    inverse=self.feature_filter_inverse,
                )
            else:
                self.on_progress(total_barcode_pages, total_barcode_pages, "正在保存 PDF...")
                save_pdf_atomic(out, self.output_pdf)

            result = {
                'success': True,
                'total_pages': total_barcode_pages,
                'merged_count': merged_count,
                'skipped_count': removed_count,
                'skipped_pages': removed_pages,
                'reverse_save': self.reverse_save,
                'output_path': self.output_pdf,
            }
            if filter_result:
                result["feature_filter"] = filter_result
            return result

        finally:
            for doc in (out, base, barcodes):
                if doc:
                    try:
                        doc.close()
                    except Exception:
                        pass

    def _calculate_rect(self, base_page: fitz.Page, barcode_page: fitz.Page) -> fitz.Rect:
        """计算条形码放置矩形
        
        Args:
            base_page: 基础页面
            barcode_page: 条形码页面
            
        Returns:
            fitz.Rect: 条形码放置矩形
        """
        page_w = base_page.rect.width
        page_h = base_page.rect.height
        br = barcode_page.rect

        target_w = page_w * self.params['barcode_width_ratio']
        target_h = target_w * br.height / br.width

        if target_h > self.params['max_barcode_height']:
            target_h = self.params['max_barcode_height']
            target_w = target_h * br.width / br.height

        x0 = (page_w - target_w) / 2 + self.params['x_offset']
        x1 = x0 + target_w
        y1 = page_h - self.params['bottom_margin'] + self.params['y_offset']
        y0 = y1 - target_h

        return fitz.Rect(x0, y0, x1, y1)

    def stop(self) -> None:
        """请求停止线程"""
        self._stop_event.set()

    def is_running(self) -> bool:
        """检查线程是否运行中"""
        return self.is_alive()


class BatchMergePDFWorker(threading.Thread):
    """批量PDF合并工作线程"""

    def __init__(self, base_pdf: str, barcode_jobs: list, params: Dict[str, float],
                 on_progress: Optional[Callable] = None, on_complete: Optional[Callable] = None,
                 on_error: Optional[Callable] = None, skip_keyword: Optional[str] = None,
                 reverse_save: bool = False, feature_filter_keywords: Optional[str] = None,
                 feature_filter_inverse: bool = False) -> None:
        super().__init__(daemon=False)

        self.base_pdf = base_pdf
        self.barcode_jobs = barcode_jobs
        self.params = params
        self.on_progress = on_progress or (lambda *args: None)
        self.on_complete = on_complete or (lambda *args: None)
        self.on_error = on_error or (lambda *args: None)
        self.skip_keyword = SKIP_KEYWORD if skip_keyword is None else skip_keyword
        self.reverse_save = reverse_save
        self.feature_filter_keywords = feature_filter_keywords
        self.feature_filter_inverse = feature_filter_inverse
        self._stop_event = threading.Event()
        self.result = None
        self.error = None

    def run(self) -> None:
        try:
            results = []
            total_jobs = len(self.barcode_jobs)
            for job_index, job in enumerate(self.barcode_jobs, start=1):
                if self._stop_event.is_set():
                    raise InterruptedError("操作已被用户中断")

                barcode_pdf = job["barcode_pdf"]
                output_pdf = job["output_pdf"]
                self.on_progress(
                    job_index - 1,
                    total_jobs,
                    f"开始处理第 {job_index} / {total_jobs} 个条码 PDF：{Path(barcode_pdf).name}",
                )

                worker = MergePDFWorker(
                    self.base_pdf,
                    barcode_pdf,
                    output_pdf,
                    self.params,
                    on_progress=lambda current, total, message, idx=job_index, count=total_jobs:
                        self.on_progress(current, total, f"[{idx}/{count}] {message}"),
                    skip_keyword=self.skip_keyword,
                    reverse_save=self.reverse_save,
                    feature_filter_keywords=self.feature_filter_keywords,
                    feature_filter_inverse=self.feature_filter_inverse,
                )
                worker._stop_event = self._stop_event
                result = worker._merge_pdf()
                result["barcode_pdf"] = barcode_pdf
                results.append(result)

            self.result = {
                "success": True,
                "total_jobs": total_jobs,
                "results": results,
            }
            self.on_complete(self.result)
        except Exception as e:
            self.error = str(e)
            self.on_error(self.error)

    def stop(self) -> None:
        """请求停止线程"""
        self._stop_event.set()

    def is_running(self) -> bool:
        """检查线程是否运行中"""
        return self.is_alive()
