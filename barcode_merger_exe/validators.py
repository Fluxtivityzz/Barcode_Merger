"""
参数验证与处理
"""
from typing import Dict, Union, Tuple
from config import PARAM_RANGES


class ValidationError(Exception):
    """验证错误异常"""
    pass


class ParamValidator:
    """参数验证器"""

    @staticmethod
    def validate_param(name: str, value: Union[str, float, int]) -> float:
        """验证单个参数
        
        Args:
            name: 参数名
            value: 参数值
            
        Returns:
            float: 验证后的数值
            
        Raises:
            ValidationError: 验证失败
        """
        if name not in PARAM_RANGES:
            raise ValidationError(f"Unknown parameter: {name}")

        try:
            fvalue = float(value)
        except (ValueError, TypeError):
            raise ValidationError(f"{name} must be a number, current value: {value}")

        param_config = PARAM_RANGES[name]
        min_val = param_config['min']
        max_val = param_config['max']

        if not (min_val <= fvalue <= max_val):
            raise ValidationError(
                f"{name} out of range [{min_val}, {max_val}], current value: {fvalue}"
            )

        return fvalue

    @staticmethod
    def validate_all_params(params_dict: Dict[str, Union[str, float, int]]) -> Dict[str, float]:
        """验证所有参数
        
        Args:
            params_dict: {param_name: value} 字典
            
        Returns:
            dict: {param_name: float_value} 验证后的参数字典
            
        Raises:
            ValidationError: 任何参数验证失败
        """
        validated = {}
        for name, value in params_dict.items():
            validated[name] = ParamValidator.validate_param(name, value)
        return validated

    @staticmethod
    def validate_file_path(path: str) -> str:
        """验证文件路径
        
        Args:
            path: 文件路径
            
        Raises:
            ValidationError: 文件不存在或路径无效
        """
        from pathlib import Path

        if not path or not isinstance(path, str):
            raise ValidationError("Invalid or empty file path")

        p = Path(path.strip())
        if not p.exists():
            raise ValidationError(f"File does not exist: {path}")

        if not p.is_file():
            raise ValidationError(f"Not a file: {path}")

        return str(p)

    @staticmethod
    def validate_output_path(path: str) -> str:
        """验证输出文件路径
        
        Args:
            path: 输出文件路径
            
        Returns:
            str: 规范化的路径
            
        Raises:
            ValidationError: 路径无效
        """
        from pathlib import Path

        if not path or not isinstance(path, str):
            raise ValidationError("Invalid or empty output path")

        p = Path(path.strip())
        
        # 确保父目录存在或可创建
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise ValidationError(f"Failed to create output directory: {e}")

        # 确保 .pdf 扩展名
        if p.suffix.lower() != '.pdf':
            p = p.with_suffix('.pdf')

        return str(p)

    @staticmethod
    def validate_all_files(base_pdf: str, barcode_pdf: str, output_pdf: str) -> Tuple[str, str, str]:
        """验证所有文件路径
        
        Args:
            base_pdf: 基础PDF路径
            barcode_pdf: 条形码PDF路径
            output_pdf: 输出PDF路径
            
        Returns:
            tuple: (base_pdf, barcode_pdf, output_pdf)
            
        Raises:
            ValidationError: 任何文件验证失败
        """
        base_pdf = ParamValidator.validate_file_path(base_pdf)
        barcode_pdf = ParamValidator.validate_file_path(barcode_pdf)
        output_pdf = ParamValidator.validate_output_path(output_pdf)

        return base_pdf, barcode_pdf, output_pdf
