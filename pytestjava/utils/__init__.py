"""
测试框架工具模块

包含API客户端、测试用例生成器、Git变更检测器等核心组件
"""

from .api_client import APIClient, api_client
from .test_generator import TestCaseGenerator
from .git_detector import GitChangeDetector
from .wechat_notifier import WeChatWorkNotifier

__all__ = [
    'APIClient',
    'api_client',
    'TestCaseGenerator',
    'GitChangeDetector',
    'WeChatWorkNotifier'
]