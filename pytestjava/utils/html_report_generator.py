"""
HTML报告生成器模块
生成包含详细信息的精美HTML测试报告
"""

import re
import logging
from datetime import datetime
from pathlib import Path

from utils.swagger_client import swagger_client

logger = logging.getLogger(__name__)


class HTMLReportGenerator:
    """生成具有现代样式和交互功能的HTML测试报告"""

    def __init__(self, base_dir: Path = None):
        self.base_dir = base_dir or Path(__file__).parent.parent
        self.reports_dir = self.base_dir / "test-reports"

    def generate(self, test_results: dict, changes: dict) -> str:
        """生成完整的HTML测试报告

        参数:
            test_results: 测试执行结果字典
            changes: 变更分析结果字典

        返回:
            str: 生成的报告文件路径
        """
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.reports_dir / "test-report.html"

        pass_rate = 0
        if test_results['total_tests'] > 0:
            pass_rate = (test_results['passed_tests'] / test_results['total_tests']) * 100

        status_color = "#10b981" if test_results['failed_tests'] == 0 else "#ef4444"
        status_text = "✅ 全部通过" if test_results['failed_tests'] == 0 else "❌ 存在失败"

        test_details_rows = self._generate_test_details_rows(test_results)
        failed_rows = self._generate_failed_rows(test_results)
        passed_rows = self._generate_passed_rows(test_results)
        impact_analysis_html = self._generate_impact_analysis_html(changes)
        endpoint_rows = self._generate_endpoint_rows(changes)

        html_content = self._build_html_template(
            status_color=status_color,
            status_text=status_text,
            pass_rate=pass_rate,
            test_results=test_results,
            test_details_rows=test_details_rows,
            failed_rows=failed_rows,
            passed_rows=passed_rows,
            endpoint_rows=endpoint_rows,
            impact_analysis_html=impact_analysis_html
        )

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"HTML报告已生成: {report_path}")
        return str(report_path)

    def _get_real_path_from_swagger(self, path: str, method: str) -> str:
        """将Swagger路径转换为带参数替换的真实API路径"""
        real_path = swagger_client.get_real_path(path, method)
        if real_path and real_path != path:
            real_path = re.sub(r'\{[^}]+\}', '1', real_path)
            return real_path
        return re.sub(r'\{[^}]+\}', '1', path)

    def _generate_test_details_rows(self, test_results: dict) -> str:
        """生成测试详情表的HTML行"""
        rows = ""
        for detail in test_results.get('test_details', []):
            row_status = "passed" if detail['status'] == 'PASSED' else "failed"
            row_icon = "✅" if detail['status'] == 'PASSED' else "❌"
            method = detail.get('method', 'N/A')
            method_class = f"method-{method.lower()}" if method != 'N/A' else ""
            rows += f"""
                <tr class="{row_status}">
                    <td>{row_icon}</td>
                    <td>{detail['name']}</td>
                    <td><span class="method-badge {method_class}">{method}</span></td>
                    <td class="status-{row_status}">{detail['status']}</td>
                </tr>
            """
        if not rows:
            rows = "<tr><td colspan='4' style='text-align:center;color:#888;'>暂无测试详情</td></tr>"
        return rows

    def _generate_failed_rows(self, test_results: dict) -> str:
        """生成包含错误详情的失败测试HTML行"""
        rows = ""
        for idx, fail in enumerate(test_results.get('failed_details', [])):
            error_msg = self._escape_html(fail.get('error', 'N/A'))
            request_params = self._escape_html(fail.get('request_params', 'N/A'))
            response = self._escape_html(fail.get('response', 'N/A'))
            method = fail.get('method', 'N/A')
            path = fail.get('path', 'N/A')
            method_class = f"method-{method.lower()}" if method != 'N/A' else ""

            rows += f"""
                <tr class="failed-detail">
                    <td>❌</td>
                    <td>
                        <div><strong>{fail['name']}</strong></div>
                        <div style="color:#888;font-size:0.85em;margin-top:5px;">{path}</div>
                    </td>
                    <td><span class="method-badge {method_class}">{method}</span></td>
                    <td>
                        <button class="error-btn" onclick="toggleError('fail-{idx}')">查看详情</button>
                        <div id="error-fail-{idx}" class="error-detail">
                            <div style="margin-bottom:10px;"><strong style="color:#ef4444;">❌ 错误信息:</strong></div>
                            <div style="background:rgba(239,68,68,0.1);padding:10px;border-radius:5px;margin-bottom:15px;">{error_msg}</div>
                            <div style="margin-bottom:10px;"><strong style="color:#00d9ff;">📤 请求参数:</strong></div>
                            <div style="background:rgba(0,217,255,0.1);padding:10px;border-radius:5px;margin-bottom:15px;font-family:monospace;">{request_params}</div>
                            <div style="margin-bottom:10px;"><strong style="color:#10b981;">📥 返回结果:</strong></div>
                            <div style="background:rgba(16,185,129,0.1);padding:10px;border-radius:5px;font-family:monospace;">{response}</div>
                        </div>
                    </td>
                </tr>
            """
        if not rows:
            rows = "<tr><td colspan='4' style='text-align:center;color:#10b981;'>🎉 无失败用例</td></tr>"
        return rows

    def _generate_passed_rows(self, test_results: dict) -> str:
        """生成包含详情的通过测试HTML行"""
        rows = ""
        for idx, passed in enumerate(test_results.get('passed_details', [])):
            request_params = self._escape_html(passed.get('request_params', 'N/A'))
            response = self._escape_html(passed.get('response', 'N/A'))
            method = passed.get('method', 'N/A')
            path = passed.get('path', 'N/A')
            method_class = f"method-{method.lower()}" if method != 'N/A' else ""

            rows += f"""
                <tr class="passed-detail">
                    <td>✅</td>
                    <td>
                        <div><strong>{passed['name']}</strong></div>
                        <div style="color:#888;font-size:0.85em;margin-top:5px;">{path}</div>
                    </td>
                    <td><span class="method-badge {method_class}">{method}</span></td>
                    <td>
                        <button class="success-btn" onclick="toggleError('pass-{idx}')">查看详情</button>
                        <div id="error-pass-{idx}" class="success-detail">
                            <div style="margin-bottom:10px;"><strong style="color:#00d9ff;">📤 请求参数:</strong></div>
                            <div style="background:rgba(0,217,255,0.1);padding:10px;border-radius:5px;margin-bottom:15px;font-family:monospace;">{request_params}</div>
                            <div style="margin-bottom:10px;"><strong style="color:#10b981;">📥 返回结果:</strong></div>
                            <div style="background:rgba(16,185,129,0.1);padding:10px;border-radius:5px;font-family:monospace;">{response}</div>
                        </div>
                    </td>
                </tr>
            """
        if not rows:
            rows = "<tr><td colspan='4' style='text-align:center;color:#888;'>暂无成功用例</td></tr>"
        return rows

    def _generate_impact_analysis_html(self, changes: dict) -> str:
        """生成影响分析部分的HTML"""
        html = ""
        if 'change_summary' not in changes:
            return html

        summary = changes['change_summary']

        html = f"""
        <div class="section">
            <h2>🔍 影响分析详情</h2>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 20px;">
                <div style="background: rgba(0, 217, 255, 0.1); padding: 15px; border-radius: 10px; text-align: center;">
                    <div style="font-size: 2em; color: #00d9ff; font-weight: bold;">{summary.get('total_files_changed', 0)}</div>
                    <div style="color: #888; font-size: 0.9em;">变更文件</div>
                </div>
                <div style="background: rgba(16, 185, 129, 0.1); padding: 15px; border-radius: 10px; text-align: center;">
                    <div style="font-size: 2em; color: #10b981; font-weight: bold;">{summary.get('added_methods', 0)}</div>
                    <div style="color: #888; font-size: 0.9em;">新增方法</div>
                </div>
                <div style="background: rgba(245, 158, 11, 0.1); padding: 15px; border-radius: 10px; text-align: center;">
                    <div style="font-size: 2em; color: #f59e0b; font-weight: bold;">{summary.get('modified_methods', 0)}</div>
                    <div style="color: #888; font-size: 0.9em;">修改方法</div>
                </div>
                <div style="background: rgba(239, 68, 68, 0.1); padding: 15px; border-radius: 10px; text-align: center;">
                    <div style="font-size: 2em; color: #ef4444; font-weight: bold;">{summary.get('deleted_methods', 0)}</div>
                    <div style="color: #888; font-size: 0.9em;">删除方法</div>
                </div>
            </div>
        """

        if 'files' in summary and summary['files']:
            html += """
            <h3 style="margin-top: 20px; margin-bottom: 15px; color: #00d9ff;">📁 文件变更详情</h3>
            <table>
                <thead>
                    <tr>
                        <th>文件路径</th>
                        <th style="width: 200px;">🟢 新增</th>
                        <th style="width: 200px;">🟡 修改</th>
                        <th style="width: 200px;">🔴 删除</th>
                    </tr>
                </thead>
                <tbody>
            """

            for file_path, file_changes in summary['files'].items():
                added_items = file_changes['added']
                modified_items = file_changes['modified']
                deleted_items = file_changes['deleted']

                # 有变更则打钩✓，无变更则显示-；鼠标悬停显示具体变更元素
                added_tooltip = ', '.join(added_items) if added_items else ''
                modified_tooltip = ', '.join(modified_items) if modified_items else ''
                deleted_tooltip = ', '.join(deleted_items) if deleted_items else ''

                added_cell = f'<span title="{added_tooltip}" style="color:#10b981;font-size:1.2em;font-weight:bold;">✓</span>' if added_items else '<span style="color:#555;">-</span>'
                modified_cell = f'<span title="{modified_tooltip}" style="color:#f59e0b;font-size:1.2em;font-weight:bold;">✓</span>' if modified_items else '<span style="color:#555;">-</span>'
                deleted_cell = f'<span title="{deleted_tooltip}" style="color:#ef4444;font-size:1.2em;font-weight:bold;">✓</span>' if deleted_items else '<span style="color:#555;">-</span>'

                html += f"""
                    <tr>
                        <td style="font-family: monospace; font-size: 0.9em;">{file_path}</td>
                        <td style="text-align:center;">{added_cell}</td>
                        <td style="text-align:center;">{modified_cell}</td>
                        <td style="text-align:center;">{deleted_cell}</td>
                    </tr>
                """

            html += """
                </tbody>
            </table>
            """

        html += """
        </div>
        """
        return html

    def _generate_endpoint_rows(self, changes: dict) -> str:
        """生成接口影响详情的HTML行"""
        rows = ""
        processed_endpoints = set()

        for ep in changes.get('affected_endpoints', []):
            endpoint_key = f"{ep['method']} {ep['path']}"
            if endpoint_key in processed_endpoints:
                continue
            processed_endpoints.add(endpoint_key)

            impact_type = ep.get('impact_type', 'unknown')
            confidence = ep.get('confidence', 0)

            if impact_type == 'direct_impact':
                impact_color = "#10b981"
                impact_text = "直接影响"
            elif impact_type == 'service_dependency':
                impact_color = "#f59e0b"
                impact_text = "服务依赖"
            elif impact_type == 'method_or_class_dependency':
                impact_color = "#3b82f6"
                impact_text = "方法或类依赖"
            else:
                impact_color = "#8b5cf6"
                impact_text = "间接影响"

            real_path = self._get_real_path_from_swagger(ep['path'], ep['method'])
            rows += f"""
                <tr>
                    <td><span class="method-badge method-{ep['method'].lower()}">{ep['method']}</span></td>
                    <td>{real_path}</td>
                    <td style="color: {impact_color}; font-weight: bold;">{impact_text}</td>
                    <td>{confidence:.0%}</td>
                </tr>
            """

        if not rows:
            rows = "<tr><td colspan='4' style='text-align:center;color:#888;'>暂无变更接口</td></tr>"
        return rows

    @staticmethod
    def _escape_html(text: str) -> str:
        """转义特殊HTML字符"""
        return text.replace('`', "'").replace('<', '&lt;').replace('>', '&gt;')

    def _build_html_template(self, **kwargs) -> str:
        """构建包含所有部分的完整HTML模板"""
        status_color = kwargs['status_color']
        status_text = kwargs['status_text']
        pass_rate = kwargs['pass_rate']
        test_results = kwargs['test_results']

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API 测试报告</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            min-height: 100vh;
            color: #fff;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        
        .header {{
            text-align: center;
            padding: 40px 20px;
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            margin-bottom: 30px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
        }}
        
        .header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
            background: linear-gradient(90deg, #00d9ff, #00ff88);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        
        .header .status {{
            font-size: 1.3em;
            color: {status_color};
            margin-top: 15px;
        }}
        
        .header .timestamp {{
            color: #888;
            margin-top: 10px;
            font-size: 0.9em;
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        
        .stat-card {{
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            padding: 25px;
            text-align: center;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }}
        
        .stat-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
        }}
        
        .stat-card .number {{
            font-size: 3em;
            font-weight: bold;
            margin-bottom: 10px;
        }}
        
        .stat-card .label {{
            color: #888;
            font-size: 1em;
        }}
        
        .stat-card.total .number {{ color: #00d9ff; }}
        .stat-card.passed .number {{ color: #10b981; }}
        .stat-card.failed .number {{ color: #ef4444; }}
        .stat-card.skipped .number {{ color: #f59e0b; }}
        .stat-card.rate .number {{ color: #8b5cf6; }}
        
        .progress-container {{
            background: rgba(255,255,255,0.1);
            border-radius: 10px;
            height: 30px;
            margin: 30px 0;
            overflow: hidden;
            position: relative;
        }}
        
        .progress-bar {{
            height: 100%;
            background: linear-gradient(90deg, #10b981, #00ff88);
            border-radius: 10px;
            transition: width 0.5s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            color: #fff;
        }}
        
        .section {{
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 30px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
        }}
        
        .section h2 {{
            font-size: 1.5em;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid rgba(255,255,255,0.1);
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        
        .section h2::before {{
            content: '';
            width: 4px;
            height: 24px;
            background: linear-gradient(180deg, #00d9ff, #00ff88);
            border-radius: 2px;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        
        th, td {{
            padding: 15px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}
        
        th {{
            background: rgba(255,255,255,0.05);
            font-weight: 600;
            color: #00d9ff;
        }}
        
        tr:hover {{
            background: rgba(255,255,255,0.03);
        }}
        
        .method-badge {{
            display: inline-block;
            padding: 5px 12px;
            border-radius: 5px;
            font-size: 0.85em;
            font-weight: bold;
            text-transform: uppercase;
        }}
        
        .method-get {{ background: #10b981; }}
        .method-post {{ background: #3b82f6; }}
        .method-put {{ background: #f59e0b; }}
        .method-delete {{ background: #ef4444; }}
        .method-patch {{ background: #8b5cf6; }}
        
        .status-PASSED {{ color: #10b981; font-weight: bold; }}
        .status-FAILED {{ color: #ef4444; font-weight: bold; }}
        
        tr.passed {{ background: rgba(16, 185, 129, 0.1); }}
        tr.failed {{ background: rgba(239, 68, 68, 0.1); }}
        
        .error-btn {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #fff;
            border: none;
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.85em;
            transition: all 0.3s ease;
        }}
        
        .error-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
        }}
        
        .error-detail {{
            display: none;
            margin-top: 10px;
            padding: 15px;
            background: rgba(239, 68, 68, 0.1);
            border-radius: 8px;
            border-left: 4px solid #ef4444;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 0.85em;
            white-space: pre-wrap;
            word-break: break-all;
            max-height: 400px;
            overflow-y: auto;
        }}
        
        .error-detail.show {{
            display: block;
            animation: fadeIn 0.3s ease;
        }}
        
        .success-btn {{
            background: linear-gradient(135deg, #10b981 0%, #00ff88 100%);
            color: #fff;
            border: none;
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.85em;
            transition: all 0.3s ease;
        }}
        
        .success-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(16, 185, 129, 0.4);
        }}
        
        .success-detail {{
            display: none;
            margin-top: 10px;
            padding: 15px;
            background: rgba(16, 185, 129, 0.1);
            border-radius: 8px;
            border-left: 4px solid #10b981;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 0.85em;
            white-space: pre-wrap;
            word-break: break-all;
            max-height: 400px;
            overflow-y: auto;
        }}
        
        .success-detail.show {{
            display: block;
            animation: fadeIn 0.3s ease;
        }}
        
        tr.passed-detail {{ background: rgba(16, 185, 129, 0.05); }}
        tr.failed-detail {{ background: rgba(239, 68, 68, 0.05); }}
        
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(-10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        
        .footer {{
            text-align: center;
            padding: 20px;
            color: #666;
            font-size: 0.9em;
        }}
        
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
        }}
        
        .animate-pulse {{
            animation: pulse 2s infinite;
        }}
    </style>
    <script>
        function toggleError(idx) {{
            var el = document.getElementById('error-' + idx);
            var btn = el.previousElementSibling;
            if (el.classList.contains('show')) {{
                el.classList.remove('show');
                btn.textContent = '查看详情';
            }} else {{
                el.classList.add('show');
                btn.textContent = '收起详情';
            }}
        }}
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 API 测试报告</h1>
            <div class="status">{status_text}</div>
            <div class="timestamp">生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card total">
                <div class="number">{test_results['total_tests']}</div>
                <div class="label">📊 总用例数</div>
            </div>
            <div class="stat-card passed">
                <div class="number">{test_results['passed_tests']}</div>
                <div class="label">✅ 通过</div>
            </div>
            <div class="stat-card failed">
                <div class="number">{test_results['failed_tests']}</div>
                <div class="label">❌ 失败</div>
            </div>
            <div class="stat-card skipped">
                <div class="number">{test_results['skipped_tests']}</div>
                <div class="label">⏭️ 跳过</div>
            </div>
            <div class="stat-card rate">
                <div class="number">{pass_rate:.1f}%</div>
                <div class="label">📈 通过率</div>
            </div>
        </div>
        
        <div class="progress-container">
            <div class="progress-bar" style="width: {pass_rate}%;">
                {pass_rate:.1f}% 通过率
            </div>
        </div>
        
        <div class="section">
            <h2>📋 测试详情</h2>
            <table>
                <thead>
                    <tr>
                        <th style="width: 50px;">状态</th>
                        <th>测试用例</th>
                        <th style="width: 100px;">请求方式</th>
                        <th style="width: 100px;">结果</th>
                    </tr>
                </thead>
                <tbody>
                    {kwargs['test_details_rows']}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <h2>✅ 成功详情</h2>
            <table>
                <thead>
                    <tr>
                        <th style="width: 50px;">状态</th>
                        <th>用例名称</th>
                        <th style="width: 100px;">请求方式</th>
                        <th>详情</th>
                    </tr>
                </thead>
                <tbody>
                    {kwargs['passed_rows']}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <h2>❌ 失败详情</h2>
            <table>
                <thead>
                    <tr>
                        <th style="width: 50px;">状态</th>
                        <th>用例名称</th>
                        <th style="width: 100px;">请求方式</th>
                        <th>详情</th>
                    </tr>
                </thead>
                <tbody>
                    {kwargs['failed_rows']}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <h2>🔗 变更接口</h2>
            <table>
                <thead>
                    <tr>
                        <th style="width: 100px;">方法</th>
                        <th>路径</th>
                        <th style="width: 120px;">影响类型</th>
                        <th style="width: 100px;">置信度</th>
                    </tr>
                </thead>
                <tbody>
                    {kwargs['endpoint_rows']}
                </tbody>
            </table>
        </div>
        
        {kwargs['impact_analysis_html']}
        
        <div class="footer">
            <p>Generated by API Test Framework | © 2026</p>
        </div>
    </div>
</body>
</html>"""
