import requests
import random
import json
import os
import time
import re
from bs4 import BeautifulSoup
from config import CONFIG


class CookieGenerationError(Exception):
    """自定义 Cookie 生成错误"""
    pass


class RequestHandler:
    def __init__(self):
        self.config = CONFIG["request"]
        self.session = requests.Session()

    def get_headers(self, cookie=None):
        """生成随机请求头"""
        return {
            "User-Agent": random.choice(self.config["user_agents"]),
            "Cookie": cookie if cookie else self.get_cookie()
        }

    def get_cookie(self):
        """生成或加载Cookie"""
        cookie_path = CONFIG["file"]["cookie_file"]
        last_error = None

        if os.path.exists(cookie_path):
            try:
                with open(cookie_path, 'r', encoding='utf-8') as f:
                    cookie_data = json.load(f)
                    # 确保加载的是字符串类型
                    if isinstance(cookie_data, str):
                        return cookie_data
                    else:
                        last_error = f"Cookie 文件 '{cookie_path}' 格式不正确"
            except FileNotFoundError:
                pass  # 文件不存在，继续生成
            except json.JSONDecodeError:
                last_error = f"Cookie 文件 '{cookie_path}' 解析失败"
            except Exception as e:
                last_error = f"读取 Cookie 文件时发生错误: {e}"

        # 生成新Cookie
        for attempt in range(10):
            novel_web_id = random.randint(10**18, 10**19 - 1)
            cookie = f'novel_web_id={novel_web_id}'
            try:
                resp = self.session.get(
                    'https://fanqienovel.com',
                    headers={"User-Agent": random.choice(self.config["user_agents"])},
                    cookies={"novel_web_id": str(novel_web_id)},
                    timeout=10
                )
                if resp.ok:
                    # 确保目录存在
                    os.makedirs(os.path.dirname(cookie_path), exist_ok=True)
                    with open(cookie_path, 'w', encoding='utf-8') as f:
                        json.dump(cookie, f, ensure_ascii=False, indent=4)
                    return cookie
            except Exception as e:
                last_error = f"Cookie生成失败(尝试{attempt + 1}/10): {str(e)}"
                time.sleep(0.5)

        raise CookieGenerationError(
            f"无法获取有效Cookie\n"
            f"可能原因:\n"
            f"1. 网络连接问题\n"
            f"2. 番茄小说服务器限制\n"
            f"3. 文件权限问题\n"
            f"最后一次错误: {last_error}"
        )

    # =========================
    # 新增：URL 入口解析 book_id
    # =========================
    @staticmethod
    def _extract_book_id_from_html(html: str) -> str | None:
        """
        从 HTML 中尽可能解析出 book_id（多种兜底规则）
        返回字符串 book_id 或 None
        """
        patterns = [
            r'"bookId"\s*:\s*"(\d+)"',
            r'"book_id"\s*:\s*"(\d+)"',
            r'"book_id"\s*:\s*(\d+)',
            r'"bookId"\s*:\s*(\d+)',
            r'/page/(\d+)',  # 兜底：页面里直接出现 /page/{book_id}
        ]
        for p in patterns:
            m = re.search(p, html)
            if m:
                return m.group(1)
        return None

    def parse_book_id_from_reader_url(self, reader_url: str) -> str:
        """
        从 /reader/... 页面中解析真正的 book_id
        例如:
        https://fanqienovel.com/reader/7462275513550127641?source=...
        """
        response = self.session.get(reader_url, headers=self.get_headers())
        if response.status_code != 200:
            raise ConnectionError(f"无法访问 reader 页面，状态码: {response.status_code}")

        book_id = self._extract_book_id_from_html(response.text)
        if not book_id:
            raise ValueError("未能从 reader 页面解析出 book_id（可能页面结构更新，需要调整正则）")
        return book_id

    def parse_book_id_from_keyword_url(self, keyword_url: str) -> str:
        """
        从 /keyword/... 页面中解析真正的 book_id
        例如:
        https://fanqienovel.com/keyword/7504767984825747465
        """
        response = self.session.get(keyword_url, headers=self.get_headers())
        if response.status_code != 200:
            raise ConnectionError(f"无法访问 keyword 页面，状态码: {response.status_code}")

        book_id = self._extract_book_id_from_html(response.text)
        if not book_id:
            raise ValueError("未能从 keyword 页面解析出 book_id（可能页面结构更新，需要调整正则）")
        return book_id

    def book_id_from_any_url(self, url_or_id: str) -> str:
        """
        支持输入：
        1) 纯数字 book_id: "1234567890"
        2) page 链接: https://fanqienovel.com/page/1234567890
        3) reader 链接: https://fanqienovel.com/reader/xxxxxxxxxxxx?...
        4) keyword 链接: https://fanqienovel.com/keyword/xxxxxxxxxxxx
        返回真正的 book_id（字符串）
        """
        s = (url_or_id or "").strip()

        # 纯数字
        if re.fullmatch(r"\d+", s):
            return s

        # page 链接
        m = re.search(r"fanqienovel\.com/page/(\d+)", s)
        if m:
            return m.group(1)

        # reader 链接
        if "fanqienovel.com/reader/" in s:
            return self.parse_book_id_from_reader_url(s)

        # keyword 链接
        if "fanqienovel.com/keyword/" in s:
            return self.parse_book_id_from_keyword_url(s)

        # 兜底：抓页面再找 book_id
        try:
            resp = self.session.get(s, headers=self.get_headers(), timeout=self.config.get("request_timeout", 10))
            if resp.status_code == 200:
                book_id = self._extract_book_id_from_html(resp.text)
                if book_id:
                    return book_id
        except Exception:
            pass

        raise ValueError(f"无法从输入解析 book_id: {url_or_id}")

    # =========================
    # 你原本的逻辑：保持不动
    # =========================
    def get_book_info(self, book_id):
        """获取书名、作者、简介"""
        url = f'https://fanqienovel.com/page/{book_id}'
        response = self.session.get(url, headers=self.get_headers())
        if response.status_code != 200:
            print(f"网络请求失败，状态码: {response.status_code}")
            return None, None, None

        soup = BeautifulSoup(response.text, 'html.parser')

        # 获取书名
        name_element = soup.find('h1')
        name = name_element.text if name_element else "未知书名"

        # 获取作者
        author_name_element = soup.find('div', class_='author-name')
        author_name = None
        if author_name_element:
            author_name_span = author_name_element.find('span', class_='author-name-text')
            author_name = author_name_span.text if author_name_span else "未知作者"

        # 获取简介
        description_element = soup.find('div', class_='page-abstract-content')
        description = None
        if description_element:
            description_p = description_element.find('p')
            description = description_p.text if description_p else "无简介"

        return name, author_name, description

    def extract_chapters(self, book_id):
        """解析章节列表"""
        url = f'https://api5-normal-lf.fqnovel.com/reading/bookapi/search/{book_id}/v'
        response = self.session.get(url, headers=self.get_headers())
        soup = BeautifulSoup(response.text, 'html.parser')

        chapters = []
        for idx, item in enumerate(soup.select('div.chapter-item')):
            a_tag = item.find('a')
            if not a_tag:
                continue

            raw_title = a_tag.get_text(strip=True)

            # 特殊章节
            if re.match(r'^(番外|特别篇|if线)\s*', raw_title):
                final_title = raw_title
            else:
                clean_title = re.sub(
                    r'^第[一二三四五六七八九十百千\d]+章\s*',
                    '',
                    raw_title
                ).strip()
                final_title = f"第{idx + 1}章 {clean_title}"

            chapters.append({
                "id": a_tag['href'].split('/')[-1],
                "title": final_title,
                "url": f"https://fanqienovel.com{a_tag['href']}",
                "index": idx
            })

        return chapters

    def down_text(self, chapter_id):
        """下载章节内容"""
        max_retries = self.config.get('max_retries', 3)
        retry_count = 0
        content = ""

        while retry_count < max_retries:
            try:
                api_url = f"https://api.cengui.cn/api/tomato/content.php?item_id={chapter_id}"
                response = self.session.get(api_url, timeout=self.config["request_timeout"])
                data = response.json()

                if data.get("code") == 200:
                    content = data.get("data", {}).get("content", "")

                    # 移除HTML标签
                    content = re.sub(r'<header>.*?</header>', '', content, flags=re.DOTALL)
                    content = re.sub(r'<footer>.*?</footer>', '', content, flags=re.DOTALL)
                    content = re.sub(r'</?article>', '', content)
                    content = re.sub(r'<p idx="\d+">', '\n', content)
                    content = re.sub(r'</p>', '\n', content)
                    content = re.sub(r'<[^>]+>', '', content)
                    content = re.sub(r'\\u003c|\\u003e', '', content)

                    # 处理可能的重复章节标题行
                    title = data.get("data", {}).get("title", "")
                    if title and content.startswith(title):
                        content = content[len(title):].lstrip()

                    content = re.sub(r'\n{2,}', '\n', content).strip()
                    content = '\n'.join(['    ' + line if line.strip() else line for line in content.split('\n')])
                    break
            except Exception as e:
                print(f"请求失败: {str(e)}, 重试第{retry_count + 1}次...")
                retry_count += 1
                time.sleep(1 * retry_count)

        if not content:  # 如果所有重试后 content 仍然为空
            raise ConnectionError(f"无法下载章节 {chapter_id}，API 可能已失效或网络错误。")

        return content
