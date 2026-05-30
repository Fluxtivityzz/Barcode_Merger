"""
预览文档缓存 - 避免重复打开/关闭PDF文件
"""
from pathlib import Path
from typing import Optional
import fitz
from config import PREVIEW_CACHE_MAX_SIZE


class PreviewCache:
    """PDF文档缓存管理器
    
    功能:
    - 缓存打开的PDF文档，避免重复I/O
    - 自动管理文档生命周期
    - 支持LRU淘汰策略
    """

    def __init__(self, max_size: int = PREVIEW_CACHE_MAX_SIZE) -> None:
        """初始化缓存
        
        Args:
            max_size: 最大缓存文档数
        """
        self.max_size = max_size
        self.cache = {}  # {path: (doc, access_count, file_signature)}
        self.access_order = []  # LRU追踪

    def _file_signature(self, path: str) -> Optional[tuple]:
        try:
            stat = Path(path).stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def get(self, path: str) -> Optional[fitz.Document]:
        """获取缓存的文档
        
        Args:
            path: 文件路径
            
        Returns:
            fitz.Document: PDF文档，如果文件不存在返回None
        """
        if path in self.cache:
            doc, count, signature = self.cache[path]
            current_signature = self._file_signature(path)
            if current_signature is None or current_signature != signature:
                self.remove(path)
                return None

            self.cache[path] = (doc, count + 1, signature)
            # 更新访问顺序
            if path in self.access_order:
                self.access_order.remove(path)
            self.access_order.append(path)
            return doc
        return None

    def put(self, path: str, doc: fitz.Document) -> None:
        """放入缓存
        
        Args:
            path: 文件路径
            doc: PDF文档对象
        """
        signature = self._file_signature(path)
        if signature is None:
            return

        if path in self.cache:
            # 已存在，更新访问计数
            old_doc, count, _ = self.cache[path]
            if old_doc is not doc:
                try:
                    old_doc.close()
                except Exception:
                    pass
            self.cache[path] = (doc, count + 1, signature)
            if path in self.access_order:
                self.access_order.remove(path)
            self.access_order.append(path)
            return

        # 检查缓存是否满
        if len(self.cache) >= self.max_size:
            self._evict_lru()

        self.cache[path] = (doc, 1, signature)
        self.access_order.append(path)

    def load_or_open(self, path: str) -> fitz.Document:
        """从缓存获取或打开文档
        
        Args:
            path: 文件路径
            
        Returns:
            fitz.Document: PDF文档
            
        Raises:
            Exception: 文件打开失败
        """
        doc = self.get(path)
        if doc is not None:
            return doc

        try:
            doc = fitz.open(path)
            self.put(path, doc)
            return doc
        except Exception as e:
            raise Exception(f"打开 PDF 文件失败：{path}，原因：{e}")

    def _evict_lru(self) -> None:
        """驱逐最少最近使用的文档"""
        if self.access_order:
            lru_path = self.access_order.pop(0)
            if lru_path in self.cache:
                doc, _, _ = self.cache.pop(lru_path)
                try:
                    doc.close()
                except Exception:
                    pass

    def clear(self) -> None:
        """清空所有缓存并关闭文档"""
        for path in list(self.cache.keys()):
            try:
                doc, _, _ = self.cache[path]
                if doc:
                    doc.close()
            except Exception:
                pass

        self.cache.clear()
        self.access_order.clear()

    def remove(self, path: str) -> None:
        """移除特定路径的缓存
        
        Args:
            path: 文件路径
        """
        if path in self.cache:
            try:
                doc, _, _ = self.cache.pop(path)
                if doc:
                    doc.close()
            except Exception:
                pass

            if path in self.access_order:
                self.access_order.remove(path)

    def __del__(self):
        """析构时清理缓存"""
        try:
            self.clear()
        except:
            pass
