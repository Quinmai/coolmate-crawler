import os
import re
import time
import uuid
import json
import requests
import pandas as pd
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from urllib.parse import urlparse

app = FastAPI()

OUTPUT_DIR = "/tmp/coolmate_exports"
os.makedirs(OUTPUT_DIR, exist_ok=True)

class CrawlRequest(BaseModel):
    sitemap_url: str = "https://www.coolmate.me/sitemap/product0.xml"
    max_products: int = 10
    delay_seconds: float = 2

@app.get("/")
def home():
    return {"status": "ok", "message": "Coolmate export API"}

@app.post("/crawl")
def crawl(req: CrawlRequest):
    parsed = urlparse(req.sitemap_url)
    if parsed.scheme != "https" or parsed.hostname != "www.coolmate.me":
        raise HTTPException(400, "Sitemap URL không hợp lệ")

    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(req.sitemap_url, headers=headers, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        raise HTTPException(502, f"Không đọc được sitemap: {e}")

    urls = []
    for node in root.iter():
        if node.tag.endswith("loc") and node.text:
            url = node.text.strip()
            p = urlparse(url)
            if p.scheme == "https" and p.hostname == "www.coolmate.me":
                if url not in urls:
                    urls.append(url)

    urls = urls[:max(1, min(req.max_products, 100))]
    rows = []
    failures = 0

    for i, url in enumerate(urls):
        try:
            page = requests.get(url, headers=headers, timeout=20)
            page.raise_for_status()
            soup = BeautifulSoup(page.text, "html.parser")

            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            description_tag = soup.find("meta", attrs={"name": "description"})
            description = description_tag.get("content", "") if description_tag else ""
            image_tag = soup.find("meta", property="og:image")
            image = image_tag.get("content", "") if image_tag else ""
            price_tag = soup.find("meta", property="product:price:amount")
            price = price_tag.get("content", "") if price_tag else ""

            rows.append({
                "URL": url,
                "Tên sản phẩm": title,
                "Giá": price,
                "Mô tả": description,
                "Ảnh": image
            })
        except Exception as e:
            failures += 1
            rows.append({
                "URL": url,
                "Tên sản phẩm": "",
                "Giá": "",
                "Mô tả": f"Lỗi: {e}",
                "Ảnh": ""
            })

        if i < len(urls) - 1:
            time.sleep(max(1, min(req.delay_seconds, 10)))

    filename = f"coolmate_{uuid.uuid4().hex[:8]}.xlsx"
    filepath = os.path.join(OUTPUT_DIR, filename)
    pd.DataFrame(rows).to_excel(filepath, index=False)

    base_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    return {
        "status": "success",
        "total_urls": len(urls),
        "successful_pages": len(rows) - failures,
        "failed_pages": failures,
        "download_url": f"{base_url}/download/{filename}",
        "filename": filename
    }

@app.get("/download/{filename}")
def download(filename: str):
    if not re.fullmatch(r"coolmate_[a-f0-9]+\.xlsx", filename):
        raise HTTPException(400, "Tên file không hợp lệ")

    filepath = os.path.join(OUTPUT_DIR, filename)
    if not os.path.isfile(filepath):
        raise HTTPException(404, "File không tồn tại hoặc đã hết hạn")

    return FileResponse(
        filepath,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
