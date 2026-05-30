"""
后台工作线程 - 处理耗时操作
"""
from typing import Dict, Callable, Optional, Any
import threading
import fitz
import re
import uuid
from pathlib import Path
from config import PDF_COMPRESSION, SKIP_KEYWORD


def normalize_text(text: Optional[str]) -> str:
    """规范化文本"""
    return re.sub(r"\s+", "", text or "")


class MergePDFWorker(threading.Thread):
    """PDF合并工作线程
    
    在后台线程中执行PDF合并，避免UI卡顿
    通过回调函数向主线程报告进度
    """

    def __init__(self, base_pdf: str, barcode_pdf: str, output_pdf: str, params: Dict[str, float], 
                 on_progress: Optional[Callable] = None, on_complete: Optional[Callable] = None, 
                 on_error: Optional[Callable] = None, skip_keyword: Optional[str] = None) -> None:
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

            removed_count = 0
            merged_count = 0
            valid_index_set = set(valid_indices)

            for i in range(total_barcode_pages):
                # 检查停止标志
                if self._stop_event.is_set():
                    raise InterruptedError("操作已被用户中断")

                page_number = i + 1
                barcode_page = barcodes[i]

                # 检查跳过关键词
                if i not in valid_index_set:
                    removed_count += 1
                    self.on_progress(i, total_barcode_pages, f"已跳过：第 {page_number} 页")
                    continue

                # 执行合并
                if len(base) == 1:
                    base_page_index = 0
                elif len(base) == total_barcode_pages:
                    base_page_index = i
                else:
                    base_page_index = merged_count
                out.insert_pdf(base, from_page=base_page_index, to_page=base_page_index)
                page = out[-1]
                target_rect = self._calculate_rect(page, barcode_page)
                page.show_pdf_page(target_rect, barcodes, i)
                merged_count += 1

                self.on_progress(i, total_barcode_pages, 
                               f"正在合并：条码第 {page_number} 页 + 底板第 {base_page_index + 1} 页（已合并 {merged_count} 页）")

            # 保存输出
            self.on_progress(total_barcode_pages, total_barcode_pages, "正在保存 PDF...")
            out_path = Path(self.output_pdf)
            temp_path = out_path.with_name(
                f".{out_path.stem}.{uuid.uuid4().hex}.tmp{out_path.suffix}"
            )
            if temp_path.exists():
                temp_path.unlink()

            try:
                out.save(str(temp_path),
                        garbage=PDF_COMPRESSION['garbage'], 
                        deflate=PDF_COMPRESSION['deflate'])
                temp_path.replace(out_path)
            except Exception:
                if temp_path.exists():
                    temp_path.unlink()
                raise

            return {
                'success': True,
                'total_pages': total_barcode_pages,
                'merged_count': merged_count,
                'skipped_count': removed_count,
                'skipped_pages': removed_pages,
                'output_path': self.output_pdf,
            }

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
