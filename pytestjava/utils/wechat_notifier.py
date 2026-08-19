"""企业微信通知模块

通过企业微信Webhook发送测试报告通知。
支持消息类型：
- Markdown消息：包含测试统计、失败详情
- 图片消息：测试报告截图
"""
import os
import base64
import hashlib
import logging
import requests
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

logger = logging.getLogger(__name__)


class WeChatWorkNotifier:
    """发送测试结果到企业微信 - 单条消息包含图片和报告信息"""

    def __init__(self):
        pass

    def _get_webhook_url(self) -> Optional[str]:
        """从环境变量获取企业微信Webhook URL"""
        webhook_url = os.getenv("WECHAT_WORK_WEBHOOK_URL")
        webhook_key = os.getenv("WECHAT_WORK_KEY")
        if not webhook_url or not webhook_key:
            return None
        return f"{webhook_url}?key={webhook_key}"

    def send_test_report(self, test_results: Dict[str, Any], 
                         report_image_path: str = None,
                         report_html_path: str = None) -> bool:
        """将测试结果作为一条通知发送，可选附带图片
        
        策略:
        - 主要：发送1条包含所有文本内容的markdown消息（统计信息、失败详情、文件信息）
        - 次要：如果有图片，发送1条纯图片消息（无重复文本）
        """
        webhook_url = self._get_webhook_url()
        if not webhook_url:
            logger.warning("企业微信webhook未配置，跳过通知")
            return False

        try:
            # 构建单一的综合markdown消息内容
            content = self._build_notification_content(test_results, report_image_path, report_html_path)
            
            # 发送主要markdown消息（包含所有内容）
            main_sent = self._send_markdown(webhook_url, content)
            
            if not main_sent:
                logger.error("发送主要通知失败")
                return False
            
            # 仅在图片可用时作为单独消息发送图片（无重复文本）
            if report_image_path and Path(report_image_path).exists():
                self._send_image_only(webhook_url, report_image_path)

            logger.info("测试报告通知发送成功")
            return True

        except Exception as e:
            logger.error(f"发送企业微信通知时出错: {e}")
            return False

    def _build_notification_content(self, test_results: Dict[str, Any],
                                     report_image_path: str = None,
                                     report_html_path: str = None) -> str:
        """在一条markdown消息中构建完整的通知内容"""
        total_tests = test_results.get('total_tests', 0) or 0
        passed_tests = test_results.get('passed_tests', 0) or 0
        failed_tests = test_results.get('failed_tests', 0) or 0
        skipped_tests = test_results.get('skipped_tests', 0) or 0
        success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0

        status_emoji = "✅" if failed_tests == 0 else "❌"
        status_text = "全部通过" if failed_tests == 0 else f"{failed_tests}个失败"

        lines = [
            f"**{status_emoji} API自动化测试报告 {status_text}**",
            "",
            f"> 📊 **总用例**: `{total_tests}` | 通过: `{passed_tests}` | 失败: `{failed_tests}` | 跳过: `{skipped_tests}`",
            f"> 📈 **通过率**: **{success_rate:.1f}%**",
        ]

        # 报告文件信息
        if report_html_path and Path(report_html_path).exists():
            file_size = Path(report_html_path).stat().st_size / 1024
            lines.extend([
                "",
                f"> 📎 **报告文件**: [`test-report.html`]({report_html_path}) ({file_size:.1f}KB)",
            ])

        # 图片说明
        if report_image_path and Path(report_image_path).exists():
            img_size = Path(report_image_path).stat().st_size / 1024
            lines.append(f"> 🖼️ **报告截图**: 见下方图片 ({img_size:.1f}KB)")

        # 失败详情
        failed_details = test_results.get('failed_details', [])
        if failed_details:
            lines.extend(["", "---", "", "❌ **失败用例 Top5**:", ""])
            for i, failed in enumerate(failed_details[:5], 1):
                name = failed.get('name', '未知')
                error = failed.get('error', '未知错误').replace('\n', ' ')[:80]
                method = failed.get('method', '')
                path = failed.get('path', '')
                endpoint = f"`{method} {path}`" if method else ""
                lines.append(f"> **{i}.** {name} {endpoint}")
                lines.append(f"> > `{error}`")
                lines.append("")
            
            if len(failed_details) > 5:
                lines.append(f"> ... 还有 **{len(failed_details) - 5}** 个失败用例")

        # 时间戳
        lines.extend([
            "",
            "---",
            "",
            f"> 🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ])

        return "\n".join(lines)

    def _send_image_only(self, webhook_url: str, image_path: str) -> bool:
        """仅发送图片，不附带文本"""
        try:
            with open(image_path, 'rb') as f:
                image_data = f.read()

            max_size = 2 * 1024 * 1024
            if len(image_data) > max_size:
                logger.warning(f"图片过大 ({len(image_data)/1024:.0f}KB)，跳过发送")
                return False

            message = {
                "msgtype": "image",
                "image": {
                    "base64": base64.b64encode(image_data).decode('utf-8'),
                    "md5": hashlib.md5(image_data).hexdigest()
                }
            }

            response = requests.post(webhook_url, json=message, timeout=30)
            result = response.json()

            if response.status_code == 200 and result.get('errcode') == 0:
                logger.info("报告截图发送成功")
                return True
            else:
                logger.warning(f"图片发送失败: {result}")
                return False

        except Exception as e:
            logger.error(f"发送图片时出错: {e}")
            return False

    def _send_markdown(self, webhook_url: str, content: str) -> bool:
        """发送Markdown格式消息到企业微信"""
        message = {
            "msgtype": "markdown",
            "markdown": {"content": content}
        }
        response = requests.post(webhook_url, json=message, timeout=10)
        return response.status_code == 200

    def send_simple_message(self, title: str, content: str) -> bool:
        """发送简单的Markdown格式消息"""
        webhook_url = self._get_webhook_url()
        if not webhook_url:
            return False
        try:
            return self._send_markdown(webhook_url, f"**{title}**\n\n{content}")
        except Exception as e:
            logger.error(f"发送消息时出错: {e}")
            return False
