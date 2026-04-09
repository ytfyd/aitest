"""
HTML转图片模块
将HTML报告转换成长截图图片用于企业微信通知
"""

import os
import base64
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class HTMLToImageConverter:
    """使用Playwright将HTML文件转换为图片"""

    def __init__(self):
        self._browser = None
        self._playwright = None

    def _ensure_playwright(self):
        """确保Playwright已安装且浏览器可用"""
        try:
            from playwright.sync_api import sync_playwright
            self._playwright_module = sync_playwright
            return True
        except ImportError:
            logger.warning("Playwright未安装，正在安装...")
            import subprocess
            subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            from playwright.sync_api import sync_playwright
            self._playwright_module = sync_playwright
            return True

    def convert_to_image(self, html_path: str or Path, output_path: str or Path = None) -> str:
        """将HTML文件转换为图片（长截图）

        参数:
            html_path: HTML文件路径
            output_path: 输出图片路径（可选）

        返回:
            str: 生成的图片文件路径
        """
        import sys
        
        html_path = Path(html_path)
        
        if output_path is None:
            output_path = html_path.with_suffix('.png')
        else:
            output_path = Path(output_path)

        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu'
                    ]
                )
                
                page = browser.new_page()
                
                # 加载HTML文件
                page.goto(f'file:///{html_path.absolute()}', wait_until='networkidle')
                
                # 等待内容渲染完成
                page.wait_for_timeout(1000)
                
                # 获取完整页面高度用于长截图
                body_height = page.evaluate('document.body.scrollHeight')
                
                # 设置视口以捕获全部内容
                viewport_width = 1280
                page.set_viewport_size({'width': viewport_width, 'height': body_height})
                
                # 截取全页面截图
                page.screenshot(
                    path=str(output_path),
                    full_page=True,
                    type='png'
                )
                
                browser.close()

            logger.info(f"截图已保存: {output_path}")
            
            if output_path.exists():
                file_size = output_path.stat().st_size / 1024
                logger.info(f"图片大小: {file_size:.1f} KB")
            
            return str(output_path)

        except ImportError:
            logger.error("Playwright未安装。请执行: pip install playwright && playwright install chromium")
            raise
        except Exception as e:
            logger.error(f"HTML转图片失败: {e}")
            raise

    def convert_html_content_to_image(self, html_content: str, output_path: str or Path = None) -> str:
        """将HTML字符串内容转换为图片

        参数:
            html_content: HTML字符串内容
            output_path: 输出图片路径（可选）

        返回:
            str: 生成的图片文件路径
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
            f.write(html_content)
            temp_html_path = f.name

        try:
            return self.convert_to_image(temp_html_path, output_path)
        finally:
            if os.path.exists(temp_html_path):
                os.unlink(temp_html_path)

    def get_base64_image(self, image_path: str or Path) -> str:
        """将图片转换为base64字符串用于API上传

        参数:
            image_path: 图片文件路径

        返回:
            str: Base64编码的图片字符串
        """
        with open(image_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')


class FallbackImageGenerator:
    """当Playwright不可用时使用PIL的回退图片生成器"""

    @staticmethod
    def generate_text_report_image(test_results: dict, output_path: str or Path) -> str:
        """使用PIL生成简单的基于文本的报告图片"""
        try:
            from PIL import Image, ImageDraw, ImageFont
            import textwrap
            
            output_path = Path(output_path)
            
            total_tests = test_results.get('total_tests', 0) or 0
            passed_tests = test_results.get('passed_tests', 0) or 0
            failed_tests = test_results.get('failed_tests', 0) or 0
            skipped_tests = test_results.get('skipped_tests', 0) or 0
            
            success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
            
            img_width = 800
            padding = 40
            line_height = 30
            
            lines = [
                "API 测试报告",
                "",
                f"总用例数: {total_tests}",
                f"通过: {passed_tests} ✅",
                f"失败: {failed_tests} ❌",
                f"跳过: {skipped_tests} ⏭️",
                f"成功率: {success_rate:.1f}%",
                "",
            ]
            
            changed_files = test_results.get('changed_files') or []
            affected_endpoints = test_results.get('affected_endpoints') or []
            
            lines.extend([
                f"变更文件: {len(changed_files)}",
                f"影响接口: {len(affected_endpoints)}",
                "",
            ])
            
            failed_details = test_results.get('failed_details', [])
            if failed_details:
                lines.append("❌ 失败用例:")
                for i, fail in enumerate(failed_details[:5], 1):
                    name = fail.get('name', '未知')
                    error = fail.get('error', '未知错误')[:50]
                    lines.append(f"{i}. {name}: {error}")
            
            img_height = len(lines) * line_height + padding * 2
            
            img = Image.new('RGB', (img_width, img_height), color='#1a1a2e')
            draw = ImageDraw.Draw(img)
            
            try:
                font_large = ImageFont.truetype("arial.ttf", 28)
                font_normal = ImageFont.truetype("arial.ttf", 20)
            except:
                font_large = ImageFont.load_default()
                font_normal = ImageFont.load_default()
            
            y = padding
            for i, line in enumerate(lines):
                if i == 0:
                    draw.text((padding, y), line, fill='#00d9ff', font=font_large)
                    y += int(line_height * 1.5)
                else:
                    draw.text((padding, y), line, fill='#ffffff', font=font_normal)
                    y += line_height
            
            img.save(str(output_path), 'PNG', quality=95)
            logger.info(f"回退图片已保存: {output_path}")
            
            return str(output_path)
            
        except ImportError:
            logger.warning("PIL不可用，无法生成回退图片")
            return None
        except Exception as e:
            logger.error(f"生成回退图片失败: {e}")
            return None


def html_to_image(html_path: str or Path, output_path: str or Path = None) -> str:
    """便捷函数：将HTML转换为图片

    参数:
        html_path: HTML文件路径
        output_path: 输出图片路径（可选）

    返回:
        str: 生成的图片文件路径
    """
    converter = HTMLToImageConverter()
    return converter.convert_to_image(html_path, output_path)
