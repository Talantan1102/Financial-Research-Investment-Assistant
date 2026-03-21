# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""错误处理模块 - MCP Server 错误处理

核心原则：
1. 不猜测、不假设、不搪塞
2. 任何错误立即停止，向用户报告问题
3. 提供选项让用户选择下一步
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import logging
import traceback

logger = logging.getLogger("ErrorHandler")


class ErrorType(Enum):
    """错误类型枚举"""
    API_ERROR = "api_error"              # API调用错误（限流、超时等）
    DATA_NOT_AVAILABLE = "data_not_available"  # 数据不存在
    DATA_INCOMPLETE = "data_incomplete"  # 数据不完整
    VALIDATION_ERROR = "validation_error" # 参数验证错误
    SYSTEM_ERROR = "system_error"        # 系统错误
    NETWORK_ERROR = "network_error"      # 网络错误
    RATE_LIMIT_ERROR = "rate_limit_error" # 限流错误
    AUTH_ERROR = "auth_error"            # 认证错误
    CONFIG_ERROR = "config_error"        # 配置错误
    CONTROL_FLOW_ERROR = "control_flow_error"  # 控制流错误
    UNKNOWN_ERROR = "unknown_error"      # 未知错误


class ErrorSeverity(Enum):
    """错误严重程度"""
    CRITICAL = "critical"    # 严重错误，必须停止
    HIGH = "high"           # 高优先级错误，建议停止
    MEDIUM = "medium"       # 中等错误，可以继续但需提示
    LOW = "low"             # 低优先级错误，可以忽略


@dataclass
class ErrorInfo:
    """错误信息"""
    error_type: ErrorType
    error_code: str
    message: str
    timestamp: str
    tool: Optional[str] = None
    skill: Optional[str] = None
    severity: ErrorSeverity = ErrorSeverity.HIGH
    is_critical: bool = False
    original_exception: Optional[Exception] = None
    stack_trace: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "error_type": self.error_type.value,
            "error_code": self.error_code,
            "message": self.message,
            "timestamp": self.timestamp,
            "tool": self.tool,
            "skill": self.skill,
            "severity": self.severity.value,
            "is_critical": self.is_critical,
            "context": self.context
        }


@dataclass
class UserOption:
    """用户选项"""
    action: str
    description: str
    recommended: bool = False
    warning: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "action": self.action,
            "description": self.description,
            "recommended": self.recommended
        }
        if self.warning:
            result["warning"] = self.warning
        return result


@dataclass
class ErrorReport:
    """错误报告"""
    status: str  # "PARTIAL_FAILURE" | "COMPLETE_FAILURE"
    errors: List[ErrorInfo]
    available_data: Dict[str, List[str]]
    missing_data: List[str]
    user_options: List[UserOption]
    execution_summary: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "errors": [e.to_dict() for e in self.errors],
            "available_data": self.available_data,
            "missing_data": self.missing_data,
            "user_options": [o.to_dict() for o in self.user_options],
            "execution_summary": self.execution_summary
        }


class ErrorClassifier:
    """错误分类器"""
    
    # 错误模式映射
    ERROR_PATTERNS = {
        # API限流
        "rate limit": (ErrorType.RATE_LIMIT_ERROR, ErrorSeverity.CRITICAL, "API_RATE_LIMIT"),
        "too many requests": (ErrorType.RATE_LIMIT_ERROR, ErrorSeverity.CRITICAL, "API_RATE_LIMIT"),
        "积分": (ErrorType.RATE_LIMIT_ERROR, ErrorSeverity.CRITICAL, "API_RATE_LIMIT"),
        "points": (ErrorType.RATE_LIMIT_ERROR, ErrorSeverity.CRITICAL, "API_RATE_LIMIT"),
        
        # 网络错误
        "timeout": (ErrorType.NETWORK_ERROR, ErrorSeverity.HIGH, "NETWORK_TIMEOUT"),
        "connection": (ErrorType.NETWORK_ERROR, ErrorSeverity.HIGH, "NETWORK_ERROR"),
        "network": (ErrorType.NETWORK_ERROR, ErrorSeverity.HIGH, "NETWORK_ERROR"),
        
        # 数据不存在
        "not found": (ErrorType.DATA_NOT_AVAILABLE, ErrorSeverity.HIGH, "DATA_NOT_FOUND"),
        "未找到": (ErrorType.DATA_NOT_AVAILABLE, ErrorSeverity.HIGH, "DATA_NOT_FOUND"),
        "不存在": (ErrorType.DATA_NOT_AVAILABLE, ErrorSeverity.HIGH, "DATA_NOT_FOUND"),
        "no data": (ErrorType.DATA_NOT_AVAILABLE, ErrorSeverity.HIGH, "DATA_NOT_FOUND"),
        
        # 验证错误
        "invalid": (ErrorType.VALIDATION_ERROR, ErrorSeverity.MEDIUM, "VALIDATION_ERROR"),
        "validation": (ErrorType.VALIDATION_ERROR, ErrorSeverity.MEDIUM, "VALIDATION_ERROR"),
        "required": (ErrorType.VALIDATION_ERROR, ErrorSeverity.MEDIUM, "MISSING_REQUIRED_PARAM"),
        "missing": (ErrorType.VALIDATION_ERROR, ErrorSeverity.MEDIUM, "MISSING_REQUIRED_PARAM"),
        
        # 认证错误
        "unauthorized": (ErrorType.AUTH_ERROR, ErrorSeverity.CRITICAL, "AUTH_ERROR"),
        "unauthenticated": (ErrorType.AUTH_ERROR, ErrorSeverity.CRITICAL, "AUTH_ERROR"),
        "token": (ErrorType.AUTH_ERROR, ErrorSeverity.CRITICAL, "AUTH_ERROR"),
        
        # 配置错误
        "config": (ErrorType.CONFIG_ERROR, ErrorSeverity.CRITICAL, "CONFIG_ERROR"),
        "environment": (ErrorType.CONFIG_ERROR, ErrorSeverity.CRITICAL, "CONFIG_ERROR"),
        "not initialized": (ErrorType.CONFIG_ERROR, ErrorSeverity.CRITICAL, "NOT_INITIALIZED"),
    }
    
    @classmethod
    def classify(cls, exception: Exception, tool: str = None, skill: str = None) -> ErrorInfo:
        """
        分类错误
        
        Args:
            exception: 异常对象
            tool: 工具名称
            skill: Skill名称
            
        Returns:
            ErrorInfo 错误信息
        """
        error_msg = str(exception).lower()
        timestamp = datetime.now().isoformat()
        
        # 匹配错误模式
        for pattern, (error_type, severity, error_code) in cls.ERROR_PATTERNS.items():
            if pattern in error_msg:
                return ErrorInfo(
                    error_type=error_type,
                    error_code=error_code,
                    message=str(exception),
                    timestamp=timestamp,
                    tool=tool,
                    skill=skill,
                    severity=severity,
                    is_critical=severity == ErrorSeverity.CRITICAL,
                    original_exception=exception,
                    stack_trace=traceback.format_exc()
                )
        
        # 默认分类为未知错误
        return ErrorInfo(
            error_type=ErrorType.UNKNOWN_ERROR,
            error_code="UNKNOWN_ERROR",
            message=str(exception),
            timestamp=timestamp,
            tool=tool,
            skill=skill,
            severity=ErrorSeverity.HIGH,
            is_critical=False,
            original_exception=exception,
            stack_trace=traceback.format_exc()
        )


class ErrorHandler:
    """错误处理器"""
    
    def __init__(self):
        self.error_history: List[ErrorInfo] = []
    
    def handle_error(
        self,
        error: ErrorInfo,
        available_data: Dict[str, List[str]] = None,
        missing_data: List[str] = None,
        execution_summary: Dict[str, Any] = None
    ) -> ErrorReport:
        """
        处理错误并生成报告
        
        Args:
            error: 错误信息
            available_data: 可用的数据
            missing_data: 缺失的数据
            execution_summary: 执行摘要
            
        Returns:
            ErrorReport 错误报告
        """
        self.error_history.append(error)
        
        # 生成用户选项
        user_options = self._generate_user_options(error)
        
        # 确定状态
        status = "COMPLETE_FAILURE" if error.is_critical else "PARTIAL_FAILURE"
        
        return ErrorReport(
            status=status,
            errors=[error],
            available_data=available_data or {},
            missing_data=missing_data or [],
            user_options=user_options,
            execution_summary=execution_summary or {}
        )
    
    def handle_multiple_errors(
        self,
        errors: List[ErrorInfo],
        available_data: Dict[str, List[str]] = None,
        missing_data: List[str] = None,
        execution_summary: Dict[str, Any] = None
    ) -> ErrorReport:
        """
        处理多个错误
        
        Args:
            errors: 错误列表
            available_data: 可用的数据
            missing_data: 缺失的数据
            execution_summary: 执行摘要
            
        Returns:
            ErrorReport 错误报告
        """
        self.error_history.extend(errors)
        
        # 检查是否有严重错误
        has_critical = any(e.is_critical for e in errors)
        status = "COMPLETE_FAILURE" if has_critical else "PARTIAL_FAILURE"
        
        # 生成用户选项（基于最严重的错误）
        critical_errors = [e for e in errors if e.is_critical]
        if critical_errors:
            user_options = self._generate_user_options(critical_errors[0])
        else:
            user_options = self._generate_user_options(errors[0])
        
        return ErrorReport(
            status=status,
            errors=errors,
            available_data=available_data or {},
            missing_data=missing_data or [],
            user_options=user_options,
            execution_summary=execution_summary or {}
        )
    
    def _generate_user_options(self, error: ErrorInfo) -> List[UserOption]:
        """根据错误类型生成用户选项"""
        options = []
        
        if error.error_type == ErrorType.RATE_LIMIT_ERROR:
            options.append(UserOption(
                action="retry",
                description="等待60秒后重试",
                recommended=True
            ))
            options.append(UserOption(
                action="continue",
                description="基于现有数据继续(有风险)",
                warning="数据可能不完整"
            ))
            options.append(UserOption(
                action="abort",
                description="终止当前查询，稍后再试"
            ))
        
        elif error.error_type == ErrorType.DATA_NOT_AVAILABLE:
            options.append(UserOption(
                action="skip",
                description="跳过此数据项，继续分析其他数据",
                recommended=True
            ))
            options.append(UserOption(
                action="alternative",
                description="使用替代数据源"
            ))
            options.append(UserOption(
                action="abort",
                description="终止当前查询"
            ))
        
        elif error.error_type == ErrorType.VALIDATION_ERROR:
            options.append(UserOption(
                action="correct",
                description="修正输入参数后重试",
                recommended=True
            ))
            options.append(UserOption(
                action="help",
                description="查看参数帮助信息"
            ))
        
        elif error.error_type == ErrorType.NETWORK_ERROR:
            options.append(UserOption(
                action="retry",
                description="立即重试",
                recommended=True
            ))
            options.append(UserOption(
                action="continue",
                description="基于缓存数据继续",
                warning="数据可能不是最新的"
            ))
            options.append(UserOption(
                action="abort",
                description="终止当前查询，检查网络后重试"
            ))
        
        elif error.error_type == ErrorType.AUTH_ERROR:
            options.append(UserOption(
                action="config",
                description="检查API密钥配置",
                recommended=True
            ))
            options.append(UserOption(
                action="abort",
                description="终止当前查询"
            ))
        
        elif error.error_type == ErrorType.CONFIG_ERROR:
            options.append(UserOption(
                action="config",
                description="检查系统配置",
                recommended=True
            ))
            options.append(UserOption(
                action="help",
                description="查看配置帮助"
            ))
        
        else:
            # 默认选项
            options.append(UserOption(
                action="retry",
                description="重试",
                recommended=True
            ))
            options.append(UserOption(
                action="abort",
                description="终止当前查询"
            ))
            options.append(UserOption(
                action="continue",
                description="继续（有风险）",
                warning="可能遇到问题"
            ))
        
        return options
    
    def should_stop_execution(self, error: ErrorInfo) -> bool:
        """
        判断是否应停止执行
        
        Args:
            error: 错误信息
            
        Returns:
            是否应停止执行
        """
        # 严重错误必须停止
        if error.is_critical:
            return True
        
        # API限流停止
        if error.error_type == ErrorType.RATE_LIMIT_ERROR:
            return True
        
        # 认证错误停止
        if error.error_type == ErrorType.AUTH_ERROR:
            return True
        
        # 配置错误停止
        if error.error_type == ErrorType.CONFIG_ERROR:
            return True
        
        return False
    
    def can_continue_with_partial_data(self, errors: List[ErrorInfo]) -> tuple[bool, str]:
        """
        判断是否可以使用部分数据继续
        
        Args:
            errors: 错误列表
            
        Returns:
            (是否可以继续, 原因)
        """
        critical_errors = [e for e in errors if e.is_critical]
        
        if critical_errors:
            return False, f"存在严重错误: {critical_errors[0].message}"
        
        # 检查是否有数据不完整错误
        data_errors = [e for e in errors if e.error_type in 
                      [ErrorType.DATA_NOT_AVAILABLE, ErrorType.DATA_INCOMPLETE]]
        
        if len(data_errors) == len(errors):
            # 只有数据错误，可以尝试继续
            return True, "部分数据缺失，但可以基于现有数据继续"
        
        return False, "存在非数据类错误，不建议继续"
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """获取错误统计信息"""
        if not self.error_history:
            return {"total_errors": 0}
        
        type_counts = {}
        for error in self.error_history:
            type_name = error.error_type.value
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
        
        return {
            "total_errors": len(self.error_history),
            "error_types": type_counts,
            "critical_errors": sum(1 for e in self.error_history if e.is_critical)
        }
    
    def clear_history(self):
        """清除错误历史"""
        self.error_history = []


# 全局错误处理器实例
_global_error_handler: Optional[ErrorHandler] = None


def get_error_handler() -> ErrorHandler:
    """获取全局错误处理器"""
    global _global_error_handler
    if _global_error_handler is None:
        _global_error_handler = ErrorHandler()
    return _global_error_handler


def handle_exception(
    exception: Exception,
    tool: str = None,
    skill: str = None,
    **context
) -> ErrorReport:
    """
    便捷函数：处理异常
    
    Args:
        exception: 异常对象
        tool: 工具名称
        skill: Skill名称
        **context: 额外上下文
        
    Returns:
        ErrorReport 错误报告
    """
    # 分类错误
    error_info = ErrorClassifier.classify(exception, tool, skill)
    error_info.context = context
    
    # 处理错误
    handler = get_error_handler()
    return handler.handle_error(error_info)


def format_error_for_user(report: ErrorReport) -> str:
    """
    格式化错误报告为用户友好的字符串
    
    Args:
        report: 错误报告
        
    Returns:
        格式化后的字符串
    """
    lines = []
    
    # 标题
    if report.status == "COMPLETE_FAILURE":
        lines.append("## ❌ 查询失败")
    else:
        lines.append("## ⚠️ 部分数据获取失败")
    
    lines.append("")
    
    # 错误详情
    for error in report.errors:
        lines.append(f"### 错误: {error.error_code}")
        lines.append(f"- **类型**: {error.error_type.value}")
        lines.append(f"- **工具**: {error.skill}.{error.tool}" if error.skill and error.tool else "")
        lines.append(f"- **信息**: {error.message}")
        lines.append(f"- **时间**: {error.timestamp}")
        lines.append("")
    
    # 可用数据
    if report.available_data:
        lines.append("### ✅ 成功获取的数据")
        for skill, tools in report.available_data.items():
            lines.append(f"- **{skill}**: {', '.join(tools)}")
        lines.append("")
    
    # 缺失数据
    if report.missing_data:
        lines.append("### ❌ 缺失的数据")
        for item in report.missing_data:
            lines.append(f"- {item}")
        lines.append("")
    
    # 用户选项
    lines.append("### 💡 您可以选择:")
    for i, option in enumerate(report.user_options, 1):
        prefix = "✅" if option.recommended else "⭕"
        lines.append(f"{prefix} **{i}. {option.action}**: {option.description}")
        if option.warning:
            lines.append(f"   ⚠️ 注意: {option.warning}")
    
    return "\n".join(lines)
