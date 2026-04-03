import os
import json
import requests
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

from config.settings import settings


class WeChatWorkNotifier:
    """Send test results to WeChat Work"""
    
    def __init__(self):
        self.webhook_url = None
    
    def _get_webhook_url(self) -> Optional[str]:
        """Get webhook URL, constructing it only if key is available"""
        webhook_url = os.getenv("WECHAT_WORK_WEBHOOK_URL")
        webhook_key = os.getenv("WECHAT_WORK_KEY")
        
        if not webhook_url or not webhook_key:
            return None
        return f"{webhook_url}?key={webhook_key}"
    
    def send_test_report(self, test_results: Dict[str, Any]) -> bool:
        """Send test results to WeChat Work"""
        webhook_url = self._get_webhook_url()
        if not webhook_url:
            print("WeChat Work webhook key not configured, skipping notification")
            return False
        
        try:
            message = self._build_message(test_results)
            response = requests.post(
                webhook_url,
                json=message,
                timeout=10
            )
            
            if response.status_code == 200:
                print("Test report sent to WeChat Work successfully")
                return True
            else:
                print(f"Failed to send report: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"Error sending WeChat Work notification: {e}")
            return False
    
    def _build_message(self, test_results: Dict[str, Any]) -> Dict[str, Any]:
        """Build WeChat Work message format"""
        total_tests = test_results.get('total_tests', 0)
        passed_tests = test_results.get('passed_tests', 0)
        failed_tests = test_results.get('failed_tests', 0)
        skipped_tests = test_results.get('skipped_tests', 0)
        
        success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
        
        # Determine message color based on success rate
        color = "info"
        if success_rate >= 90:
            color = "green"
        elif success_rate >= 80:
            color = "yellow"
        else:
            color = "red"
        
        # Build message content
        content = f"""API测试报告

📊 测试统计:
- 总用例数: {total_tests}
- 通过: {passed_tests} ✅
- 失败: {failed_tests} ❌
- 跳过: {skipped_tests} ⏭️
- 成功率: {success_rate:.1f}%

🔄 变更检测:
- 变更文件: {len(test_results.get('changed_files', []))}
- 影响接口: {len(test_results.get('affected_endpoints', []))}

🔗 构建信息:
- 提交: {test_results.get('commit_sha', 'N/A')[:8]}
- 构建: {test_results.get('build_number', 'N/A')}
"""
        
        # Add failed tests details if any
        failed_details = test_results.get('failed_details', [])
        if failed_details:
            content += "\n❌ 失败用例:\n"
            for i, failed in enumerate(failed_details[:5], 1):  # Show first 5 failures
                content += f"{i}. {failed.get('name', 'Unknown')}: {failed.get('error', 'Unknown error')}\n"
            
            if len(failed_details) > 5:
                content += f"... 还有 {len(failed_details) - 5} 个失败用例\n"
        
        message = {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }
        
        return message
    
    def send_simple_message(self, title: str, content: str, color: str = "info") -> bool:
        """Send a simple message to WeChat Work"""
        webhook_url = self._get_webhook_url()
        if not webhook_url:
            print("WeChat Work webhook key not configured, skipping notification")
            return False
        
        try:
            message = {
                "msgtype": "markdown",
                "markdown": {
                    "content": f"**{title}**\n\n{content}"
                }
            }
            
            response = requests.post(
                webhook_url,
                json=message,
                timeout=10
            )
            
            return response.status_code == 200
                
        except Exception as e:
            print(f"Error sending WeChat Work message: {e}")
            return False