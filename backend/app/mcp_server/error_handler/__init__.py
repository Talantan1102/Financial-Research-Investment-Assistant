"""Error Handler - 错误处理模块

实现透明的错误处理策略：
- 不猜测、不假设、不搪塞
- 任何错误立即停止，向用户报告问题
- 提供选项让用户选择下一步
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import traceback


class ErrorType(Enum):
    """错误类型"""
    API_ERROR = "api_error"              # API限流/超时
    DATA_NOT_AVAILABLE = "data_not_available"  # 数据不存在
    DATA_INCOMPLETE = "data_incomplete"  # 数据不完整
    VALIDATION_ERROR = "validation_error"  # 参数错误
    SYSTEM_ERROR = "system_error"        # 系统错误
    NETWORK_ERROR = "network_error"      # 网络错误
    RATE_LIMIT = "rate_limit"            # 限流错误
    PERMISSION_ERROR = "permission_error"  # 权限错误


class ErrorSeverity(Enum):
    """错误严重级别"""
    CRITICAL = "critical"    # 关键错误，必须停止
    HIGH = "high"           # 高级别错误，建议停止
    MEDIUM = "medium"       # 中级别错误，可继续但需提示
    LOW = "low"             # 低级别错误，可忽略


@dataclass
class ErrorInfo:
    """错误信息"""
    error_type: ErrorType
    error_code: str
    message: str
    tool: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    stack_trace: Optional[str] = None
    is_critical: bool = False
    suggested_action: Optional[str] = None
    retry_after_seconds: Optional[int] = None


@dataclass
class UserOption:
    """用户选项"""
    action: str
    description: str
    recommended: bool = False
    warning: Optional[str] = None


class ErrorHandler:
    """错误处理器"""
    
    # 错误类型到严重级别的映射
    ERROR_SEVERITY_MAP = {
        ErrorType.API_ERROR: ErrorSeverity.HIGH,
        ErrorType.DATA_NOT_AVAILABLE: ErrorSeverity.HIGH,
        ErrorType.DATA_INCOMPLETE: ErrorSeverity.MEDIUM,
        ErrorType.VALIDATION_ERROR: ErrorSeverity.MEDIUM,
        ErrorType.SYSTEM_ERROR: ErrorSeverity.CRITICAL,
        ErrorType.NETWORK_ERROR: ErrorSeverity.HIGH,
        ErrorType.RATE_LIMIT: ErrorSeverity.HIGH,
        ErrorType.PERMISSION_ERROR: ErrorSeverity.CRITICAL,
    }
    
    # 关键数据项 - 这些数据的缺失会导致分析无法继续
    CRITICAL_DATA_ITEMS = [
        "roe", "roa", "gross_margin", "net_margin",  # 财务指标
        "pe", "pb", "total_mv",  # 估值指标
        "close", "volume",  # 基础行情
    ]
    
    def __init__(self):
        self.error_history: List[ErrorInfo] = []
        self.max_errors_before_stop = 3
    
    def handle_error(
        self,
        error: Exception,
        tool: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> ErrorInfo:
        """
        处理错误
        
        Args:
            error: 异常对象
            tool: 发生错误的工具名
            context: 上下文信息
        
        Returns:
            ErrorInfo 错误信息
        """
        error_info = self._classify_error(error, tool)
        self.error_history.append(error_info)
        
        return error_info
    
    def _classify_error(self, error: Exception, tool: Optional[str]) -> ErrorInfo:
        """分类错误"""
        error_msg = str(error).lower()
        error_type = ErrorType.SYSTEM_ERROR
        error_code = "UNKNOWN_ERROR"
        is_critical = False
        retry_after = None
        suggested_action = None
        
        # 根据错误消息分类
        if "rate limit" in error_msg or "too many requests" in error_msg or "frequency" in error_msg:
            error_type = ErrorType.RATE_LIMIT
            error_code = "TUSHARE_RATE_LIMIT"
            retry_after = 60
            suggested_action = "请等待60秒后重试"
        
        elif "points" in error_msg or "积分" in error_msg:
            error_type = ErrorType.PERMISSION_ERROR
            error_code = "INSUFFICIENT_POINTS"
            suggested_action = "请联系管理员充值积分或升级账号"
        
        elif "network" in error_msg or "timeout" in error_msg or "connection" in error_msg:
            error_type = ErrorType.NETWORK_ERROR
            error_code = "NETWORK_ERROR"
            suggested_action = "请检查网络连接后重试"
        
        elif "not found" in error_msg or "不存在" in error_msg or "未找到" in error_msg:
            error_type = ErrorType.DATA_NOT_AVAILABLE
            error_code = "DATA_NOT_FOUND"
            suggested_action = "请检查股票代码是否正确"
        
        elif "invalid" in error_msg or "参数" in error_msg or "parameter" in error_msg:
            error_type = ErrorType.VALIDATION_ERROR
            error_code = "INVALID_PARAMETER"
            suggested_action = "请检查输入参数"
        
        elif "incomplete" in error_msg or "不完整" in error_msg:
            error_type = ErrorType.DATA_INCOMPLETE
            error_code = "DATA_INCOMPLETE"
            suggested_action = "数据不完整，建议稍后重试"
        
        # 判断是否为关键错误
        severity = self.ERROR_SEVERITY_MAP.get(error_type, ErrorSeverity.MEDIUM)
        is_critical = severity in [ErrorSeverity.CRITICAL, ErrorSeverity.HIGH]
        
        # 检查是否涉及关键数据
        if tool and any(item in tool.lower() for item in ["financial", "roe", "income"]):
            is_critical = True
        
        return ErrorInfo(
            error_type=error_type,
            error_code=error_code,
            message=str(error),
            tool=tool,
            timestamp=datetime.now().isoformat(),
            stack_trace=traceback.format_exc() if severity == ErrorSeverity.CRITICAL else None,
            is_critical=is_critical,
            suggested_action=suggested_action,
            retry_after_seconds=retry_after
        )
    
    def should_stop_execution(self, error_info: ErrorInfo) -> bool:
        """
        判断是否应停止执行
        
        原则：
        - 关键错误立即停止
        - 累积错误过多停止
        """
        if error_info.is_critical:
            return True
        
        # 检查累积错误数
        recent_errors = [e for e in self.error_history if e.error_type != ErrorType.DATA_INCOMPLETE]
        if len(recent_errors) >= self.max_errors_before_stop:
            return True
        
        return False
    
    def generate_user_options(self, error_info: ErrorInfo) -> List[UserOption]:
        """生成用户选项"""
        options = []
        
        # 重试选项
        if error_info.retry_after_seconds:
            options.append(UserOption(
                action="retry",
                description=f"等待{error_info.retry_after_seconds}秒后重试",
                recommended=True
            ))
        else:
            options.append(UserOption(
                action="retry",
                description="立即重试",
                recommended=False
            ))
        
        # 跳过继续选项（仅适用于非关键错误）
        if not error_info.is_critical:
            options.append(UserOption(
                action="continue",
                description="基于现有数据继续(有风险)",
                warning="缺少部分数据，分析可能不完整"
            ))
        
        # 终止选项
        options.append(UserOption(
            action="abort",
            description="终止当前查询"
        ))
        
        # 检查输入选项
        if error_info.error_type == ErrorType.VALIDATION_ERROR:
            options.append(UserOption(
                action="correct_input",
                description="修正输入参数后重试",
                recommended=True
            ))
        
        return options
    
    def format_error_response(self, error_info: ErrorInfo) -> Dict[str, Any]:
        """格式化错误响应"""
        response = {
            "status": "ERROR",
            "error": {
                "type": error_info.error_type.value,
                "code": error_info.error_code,
                "message": error_info.message,
                "tool": error_info.tool,
                "timestamp": error_info.timestamp,
                "is_critical": error_info.is_critical
            }
        }
        
        if error_info.suggested_action:
            response["error"]["suggested_action"] = error_info.suggested_action
        
        if error_info.retry_after_seconds:
            response["error"]["retry_after_seconds"] = error_info.retry_after_seconds
        
        # 生成用户选项
        options = self.generate_user_options(error_info)
        response["user_options"] = [
            {
                "action": opt.action,
                "description": opt.description,
                "recommended": opt.recommended,
                "warning": opt.warning
            }
            for opt in options
        ]
        
        return response
    
    def format_partial_failure_response(
        self,
        available_data: Dict[str, List[str]],
        missing_data: List[str],
        errors: List[ErrorInfo]
    ) -> Dict[str, Any]:
        """格式化部分失败响应"""
        return {
            "status": "PARTIAL_FAILURE",
            "available_data": available_data,
            "missing_data": missing_data,
            "errors": [
                {
                    "tool": e.tool,
                    "type": e.error_type.value,
                    "code": e.error_code,
                    "message": e.message,
                    "timestamp": e.timestamp
                }
                for e in errors
            ],
            "user_options": [
                {
                    "action": "retry",
                    "description": "重试获取失败的数据",
                    "recommended": True
                },
                {
                    "action": "continue",
                    "description": "基于现有数据继续(有风险)",
                    "warning": f"缺少以下关键数据: {', '.join(missing_data)}"
                },
                {
                    "action": "abort",
                    "description": "终止当前查询"
                }
            ]
        }
    
    def is_critical_data_missing(self, data_item: str) -> bool:
        """检查是否为关键数据缺失"""
        return any(critical in data_item.lower() for critical in self.CRITICAL_DATA_ITEMS)
    
    def get_error_history(self) -> List[Dict[str, Any]]:
        """获取错误历史"""
        return [
            {
                "type": e.error_type.value,
                "code": e.error_code,
                "message": e.message,
                "tool": e.tool,
                "timestamp": e.timestamp,
                "is_critical": e.is_critical
            }
            for e in self.error_history
        ]
    
    def clear_history(self):
        """清空错误历史"""
        self.error_history = []


# 全局错误处理器实例
_error_handler: Optional[ErrorHandler] = None


def get_error_handler() -> ErrorHandler:
    """获取错误处理器单例"""
    global _error_handler
    if _error_handler is None:
        _error_handler = ErrorHandler()
    return _error_handler


def handle_error(error: Exception, tool: Optional[str] = None) -> Dict[str, Any]:
    """便捷函数：处理错误并返回响应"""
    handler = get_error_handler()
    error_info = handler.handle_error(error, tool)
    return handler.format_error_response(error_info)
