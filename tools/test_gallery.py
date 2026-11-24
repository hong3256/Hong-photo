#!/usr/bin/env python3
"""photo-gallery-app 화면 동작 검증 (Playwright, 가짜 Apps Script).

실제 드라이브·스크립트 없이, script.google.com 요청을 가로채 가짜 응답을 준다.
확인: 빈 상태 · 연결 모달 · 그리드/앨범/검색/정렬 · 라이트박스(이전·다음·키보드·다운로드)
      · 관리자 PIN · 업로드 · 삭제 · 열람 잠금 · 사진 댓글(배지·조회·작성·삭제·XSS·구형 스크립트) · 콘솔 오류 0건
"""
import base64
import io
import json
import os
import re
import sys
import threading
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8123
BASE = "http://127.0.0.1:%d" % PORT
FAKE_URL = "https://script.google.com/macros/s/FAKE_TEST/exec"
SHOTS = os.path.join(os.path.dirname(HERE), "downloads")

failures = []
checks = 0


def check(name, cond, detail=None):
    global checks
    checks += 1
    if cond:
        print("  ✓", name)
    else:
        print("  ✗", name, str(detail)[:300] if detail is not None else "")
        failures.append(name)


def serve():
    os.chdir(HERE)

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def png_data_uri(label, color, size=(480, 360)):
    """사진처럼 보이는 가짜 이미지(하늘 그라데이션 + 해 + 산)."""
    im = Image.new("RGB", size)
    px = im.load()
    top = tuple(min(255, c + 60) for c in color)
    bottom = tuple(max(0, c - 40) for c in color)
    for y in range(size[1]):
        t = y / size[1]
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(size[0]):
            px[x, y] = c
    d = ImageDraw.Draw(im)
    seed = sum(ord(ch) for ch in str(label))
    d.ellipse([size[0] * 0.62, size[1] * 0.14, size[0] * 0.82, size[1] * 0.34], fill=(250, 226, 180))
    d.polygon([(0, size[1]), (size[0] * 0.30, size[1] * 0.45), (size[0] * 0.62, size[1])],
              fill=tuple(max(0, c - 70) for c in color))
    d.polygon([(size[0] * 0.34, size[1]), (size[0] * 0.68, size[1] * 0.55), (size[0], size[1])],
              fill=tuple(max(0, c - 95) for c in color))
    d.rectangle([0, int(size[1] * 0.9), size[0], size[1]], fill=tuple(max(0, c - 110) for c in color))
    if seed % 3 == 0:
        d.ellipse([size[0] * 0.12, size[1] * 0.62, size[0] * 0.26, size[1] * 0.86], fill=(255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=72)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


COLORS = [(163, 76, 40), (32, 71, 61), (46, 84, 122), (116, 86, 52),
          (96, 62, 106), (38, 96, 88), (140, 104, 38), (70, 74, 84)]


class Mock:
    img_calls = 0

    def __init__(self, photos, albums, locked=False, old_script=False):
        self.photos = photos
        self.albums = albums
        self.locked = locked
        self.old_script = old_script
        self.uploaded = []
        self.deleted = []
        self.comments = {}
        self.comments_added = []
        self.deleted_comments = []
        self.seq = 0
        self.cm_seq = 0
        self.images = {}
        for i, p in enumerate(photos):
            self.images[p["id"]] = png_data_uri(p["name"], COLORS[i % len(COLORS)])

    def img(self, pid):
        return self.images.get(pid) or png_data_uri(pid, (140, 140, 140))

    def handle(self, route):
        req = route.request
        url = urllib.parse.urlsplit(req.url)
        q = dict(urllib.parse.parse_qsl(url.query))
        hdr = {"access-control-allow-origin": "*", "content-type": "application/json; charset=utf-8"}

        def send(obj):
            route.fulfill(status=200, headers=hdr, body=json.dumps(obj, ensure_ascii=False))

        if req.method == "POST":
            try:
                body = json.loads(req.post_data or "{}")
            except Exception:
                return send({"ok": False, "error": "BAD_REQUEST"})
            action = body.get("action")
            if action == "auth":
                if str(body.get("pin")) != "2580":
                    return send({"ok": False, "error": "BAD_PIN", "message": "관리자 PIN이 맞지 않습니다."})
                return send({"ok": True, "admin": True})
            if action == "upload":
                if str(body.get("pin")) != "2580":
                    return send({"ok": False, "error": "BAD_PIN"})
                self.seq += 1
                pid = "UP%d" % self.seq
                album = str(body.get("album") or "")
                p = {"id": pid, "name": body.get("filename") or "up.jpg", "album": album,
                     "date": "2026-11-24T12:00:00", "dateLabel": "2026.11.24",
                     "mimeType": "image/jpeg", "size": 1234}
                self.photos.insert(0, p)
                self.uploaded.append(body)
                self.images[pid] = png_data_uri("UP", (60, 140, 100))
                return send(dict({"ok": True}, **p))
            if action == "delete":
                if str(body.get("pin")) != "2580":
                    return send({"ok": False, "error": "BAD_PIN"})
                pid = body.get("id")
                self.photos = [p for p in self.photos if p["id"] != pid]
                self.deleted.append(pid)
                return send({"ok": True, "id": pid, "trashed": True})
            if action == "addComment":
                if self.old_script:
                    return send({"ok": False, "error": "BAD_REQUEST", "message": "알 수 없는 요청입니다: addComment"})
                pid = body.get("photoId")
                if not any(p["id"] == pid for p in self.photos):
                    return send({"ok": False, "error": "NOT_FOUND", "message": "사진을 찾을 수 없습니다."})
                text = str(body.get("text") or "").strip()
                if not text:
                    return send({"ok": False, "error": "BAD_REQUEST", "message": "댓글 내용을 입력해 주세요."})
                author = str(body.get("author") or "").strip() or "익명"
                self.cm_seq += 1
                row = {"id": "C%d" % self.cm_seq, "author": author, "text": text,
                       "createdAt": "2026-11-24T13:30:00", "dateLabel": "2026.11.24 13:%02d" % (self.cm_seq % 60)}
                self.comments.setdefault(pid, []).append(row)
                self.comments_added.append(body)
                lst = self.comments[pid]
                return send({"ok": True, "photoId": pid, "comment": row, "comments": lst, "commentCount": len(lst)})
            if action == "deleteComment":
                if str(body.get("pin")) != "2580":
                    return send({"ok": False, "error": "BAD_PIN", "message": "관리자 PIN이 맞지 않습니다."})
                pid = body.get("photoId")
                cid = body.get("commentId")
                lst = self.comments.get(pid, [])
                if not any(c["id"] == cid for c in lst):
                    return send({"ok": False, "error": "NOT_FOUND", "message": "댓글을 찾을 수 없습니다."})
                lst = [c for c in lst if c["id"] != cid]
                self.comments[pid] = lst
                self.deleted_comments.append(cid)
                return send({"ok": True, "photoId": pid, "deleted": cid, "comments": lst, "commentCount": len(lst)})
            return send({"ok": False, "error": "BAD_REQUEST"})

        action = q.get("action", "ping")
        if action == "ping":
            return send({"ok": True, "app": "jinphoto", "name": "진홍 포토 갤러리", "photoCount": len(self.photos),
                         "albumCount": len({p["album"] for p in self.photos if p["album"]}), "locked": self.locked})
        if action == "login":
            if str(q.get("pin")) == "2580":
                return send({"ok": True, "token": "tok.abc", "locked": True})
            return send({"ok": False, "error": "BAD_PIN", "message": "비밀번호가 맞지 않습니다."})
        if action == "list":
            if self.locked and q.get("token") != "tok.abc":
                return send({"ok": False, "error": "LOCKED"})
            albums = {}
            for p in self.photos:
                if p["album"]:
                    albums[p["album"]] = albums.get(p["album"], 0) + 1
            photos = [dict(p, commentCount=len(self.comments.get(p["id"], []))) for p in self.photos]
            return send({"ok": True, "name": "진홍 포토 갤러리", "photos": photos,
                         "albums": [{"name": k, "count": v} for k, v in sorted(albums.items())],
                         "total": len(self.photos), "locked": self.locked})
        if action == "comments":
            if self.old_script:
                return send({"ok": False, "error": "BAD_REQUEST", "message": "알 수 없는 요청입니다: comments"})
            if self.locked and q.get("token") != "tok.abc":
                return send({"ok": False, "error": "LOCKED"})
            pid = q.get("id")
            if not any(p["id"] == pid for p in self.photos):
                return send({"ok": False, "error": "NOT_FOUND"})
            lst = self.comments.get(pid, [])
            return send({"ok": True, "photoId": pid, "comments": lst, "commentCount": len(lst)})
        if action == "img":
            Mock.img_calls += 1
            if self.locked and q.get("token") != "tok.abc":
                return send({"ok": False, "error": "LOCKED"})
            pid = q.get("id")
            if not any(p["id"] == pid for p in self.photos):
                return send({"ok": False, "error": "NOT_FOUND"})
            return send({"ok": True, "id": pid, "mimeType": "image/jpeg", "data": self.img(pid)})
        return send({"ok": False, "error": "BAD_REQUEST"})


def make_photos(n=12):
    names = ["IMG_0001.jpg", "IMG_0002.jpg", "IMG_0003.jpg", "IMG_0004.jpg", "IMG_0005.jpg",
             "kakao_1.png", "kakao_2.png", "IMG_0012.jpg", "family_1.jpg", "family_2.jpg",
             "trip_1.jpg", "trip_2.jpg"]
    albums = ["", "", "", "가족여행", "가족여행", "", "가족여행", "C-PICK 대회", "C-PICK 대회",
              "C-PICK 대회", "", ""]
    photos = []
    for i in range(n):
        day = 23 - i
        photos.append({
            "id": "P%d" % (i + 1),
            "name": names[i % len(names)],
            "album": albums[i % len(albums)],
            "date": "2026-11-%02dT10:%02d:00" % (max(1, day), i * 3 % 60),
            "dateLabel": "2026.11.%02d" % max(1, day),
            "mimeType": "image/jpeg",
            "size": 1024 * (i + 2),
        })
    return photos


def album_counts(photos):
    out = {}
    for p in photos:
        if p["album"]:
            out[p["album"]] = out.get(p["album"], 0) + 1
    return out


def box_of(page, sel):
    return page.eval_on_selector(sel, "e => { const r = e.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; }")


def new_page(browser, mock, mobile=False, url_param=True, store_url=None):
    ctx = browser.new_context(
        viewport={"width": 390, "height": 844} if mobile else {"width": 1280, "height": 900},
        device_scale_factor=2 if mobile else 1,
        is_mobile=mobile, has_touch=mobile, accept_downloads=True,
    )
    page = ctx.new_page()
    errors, page_errors, failed = [], [], []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: page_errors.append(str(e)))
    page.on("requestfailed", lambda r: failed.append(r.url + " :: " + str(r.failure)))
    page.route(re.compile(r"^https://script\.google\.com/macros/s/.*"), mock.handle)
    page.goto(BASE + "/manifest.json")
    if store_url:
        page.evaluate("(u) => localStorage.setItem('hg_sync_url', u)", store_url)
    page.goto(BASE + "/index.html" + ("?url=" + urllib.parse.quote(FAKE_URL) if url_param else ""))
    return ctx, page, errors, page_errors, failed


def main():
    httpd = serve()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()

            # ── 1. 데스크톱: 연결 전 → 연결 → 그리드/앨범/검색/정렬 → 라이트박스 ──
            print("[1] 데스크톱 — 연결·그리드·라이트박스")
            photos = make_photos()
            mock = Mock(photos, album_counts(photos))
            ctx, page, errors, page_errors, failed = new_page(browser, mock, url_param=False, store_url="none")

            page.wait_for_selector("#state:not([hidden])")
            check("연결 전 안내", "연결" in page.inner_text("#stateTitle"), page.inner_text("#stateTitle"))
            check("연결 전 상단 안내", "드라이브를 연결" in page.inner_text("#subTitle"), page.inner_text("#subTitle"))
            page.screenshot(path=os.path.join(SHOTS, "photo-app-desktop-setup.png"))

            page.click("#btnConnect")
            page.wait_for_selector("#ovConnect.show")
            page.fill("#setUrl", FAKE_URL)
            page.click("#setTest")
            page.wait_for_function("() => document.getElementById('setNote').classList.contains('ok')")
            check("연결 확인 결과", "진홍 포토 갤러리" in page.inner_text("#setNote"), page.inner_text("#setNote"))
            page.click("#setSave")
            page.wait_for_function("() => document.querySelectorAll('#gallery .card').length === 12")
            page.wait_for_function("() => document.querySelectorAll('#gallery img.ready').length >= 8")
            check("카드 12개", page.eval_on_selector_all("#gallery .card", "els => els.length") == 12)
            check("앨범 칩 3개(전체+2)", page.eval_on_selector_all("#chips .chip", "els => els.length") == 3,
                  page.eval_on_selector_all("#chips .chip", "els => els.map(e => e.textContent.trim())"))
            check("부제 사진 수", "사진 12장" in page.inner_text("#subTitle"), page.inner_text("#subTitle"))
            page.wait_for_timeout(700)
            page.mouse.move(4, 4)
            page.wait_for_timeout(200)
            page.screenshot(path=os.path.join(SHOTS, "photo-app-desktop-grid.png"), full_page=False)

            # 앨범 필터
            page.click("#chips .chip:nth-child(3)")   # 가족여행 (전체, C-PICK 대회, 가족여행 정렬)
            page.wait_for_timeout(250)
            n_album = page.eval_on_selector_all("#gallery .card", "els => els.length")
            check("앨범 필터 결과", n_album == album_counts(photos).get("가족여행"), n_album)
            page.click("#chips .chip:nth-child(1)")

            # 검색
            page.fill("#q", "IMG_0004")
            page.wait_for_timeout(320)
            check("검색 1장", page.eval_on_selector_all("#gallery .card", "els => els.length") == 1)
            page.click("#qClear")
            page.wait_for_timeout(320)
            check("검색 지우기", page.eval_on_selector_all("#gallery .card", "els => els.length") == 12)

            # 정렬
            page.select_option("#sort", "asc")
            page.wait_for_timeout(200)
            first_date = page.eval_on_selector("#gallery .card", "e => e.getAttribute('data-id')")
            oldest = sorted(photos, key=lambda p: p["date"])[0]["id"]
            check("오래된순 정렬", first_date == oldest, (first_date, oldest))
            page.select_option("#sort", "desc")
            page.wait_for_timeout(200)

            # 라이트박스
            page.click("#gallery .card:nth-child(1)")
            page.wait_for_selector("#lb.show")
            page.wait_for_function("() => document.getElementById('lbImg').classList.contains('ready')")
            check("관리자 아니면 삭제 버튼 숨김",
                  page.eval_on_selector("#lbDelete", "e => getComputedStyle(e).display === 'none'"))
            check("라이트박스 카운터", page.inner_text("#lbCount") == "1 / 12", page.inner_text("#lbCount"))
            src1 = page.eval_on_selector("#lbImg", "e => e.getAttribute('src')")
            check("라이트박스 원본 표시", src1.startswith("data:image/"), src1[:40])
            page.wait_for_timeout(600)
            page.screenshot(path=os.path.join(SHOTS, "photo-app-desktop-lightbox.png"))
            page.click("#lbNext")
            page.wait_for_timeout(400)
            check("다음 사진", page.inner_text("#lbCount") == "2 / 12", page.inner_text("#lbCount"))
            name2 = page.inner_text("#lbName")
            page.keyboard.press("ArrowLeft")
            page.wait_for_timeout(350)
            check("키보드 이전", page.inner_text("#lbCount") == "1 / 12", page.inner_text("#lbCount"))
            page.keyboard.press("ArrowRight")
            page.wait_for_timeout(350)
            check("다음 사진 이름 바뀜", page.inner_text("#lbName") == name2)

            with page.expect_download() as dl:
                page.click("#lbDownload")
            d = dl.value
            check("원본 다운로드", d.suggested_filename.endswith(".jpg"), d.suggested_filename)
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            check("Esc 닫기", not page.eval_on_selector("#lb", "e => e.classList.contains('show')"))

            check("콘솔 오류 0", len(errors) == 0, errors)
            check("페이지 오류 0", len(page_errors) == 0, page_errors)
            check("실패 요청 0", len(failed) == 0, failed)
            ctx.close()

            # ── 2. 모바일: 관리자 PIN → 업로드 → 삭제 ──
            print("[2] 모바일 — 관리자·업로드·삭제")
            photos2 = make_photos()
            mock2 = Mock(photos2, album_counts(photos2))
            ctx, page, errors, page_errors, failed = new_page(browser, mock2, mobile=True)
            page.wait_for_function("() => document.querySelectorAll('#gallery .card').length === 12")
            check("모바일 2열 그리드",
                  page.eval_on_selector("#gallery", "e => getComputedStyle(e).gridTemplateColumns.split(' ').length") == 2,
                  page.eval_on_selector("#gallery", "e => getComputedStyle(e).gridTemplateColumns"))
            check("관리자 전 FAB 숨김", not page.eval_on_selector("#fab", "e => e.classList.contains('show')"))

            page.click("#btnAdmin")
            page.wait_for_selector("#ovPin.show")
            page.fill("#pinInput", "1111")
            page.click("#pinOk")
            page.wait_for_function("() => document.getElementById('pinNote').classList.contains('show')")
            check("틀린 PIN 안내", "맞지 않" in page.inner_text("#pinNote"), page.inner_text("#pinNote"))
            page.fill("#pinInput", "2580")
            page.click("#pinOk")
            page.wait_for_selector("#fab.show")
            check("관리자 모드 FAB", page.eval_on_selector("#fab", "e => e.classList.contains('show')"))

            page.click("#fab")
            page.wait_for_selector("#ovUpload.show")
            page.set_input_files("#files", [
                os.path.join(SHOTS, "photo-app-desktop-grid.png"),
                os.path.join(SHOTS, "photo-app-desktop-lightbox.png"),
            ])
            page.wait_for_function("() => document.querySelectorAll('#fileList .th').length === 2")
            check("업로드 미리보기 2장", page.eval_on_selector_all("#fileList .th", "e => e.length") == 2)
            page.select_option("#upAlbum", "가족여행")
            page.screenshot(path=os.path.join(SHOTS, "photo-app-mobile-upload.png"))
            page.click("#upStart")
            page.wait_for_function("() => S.photos.length === 14", timeout=25000)
            check("업로드 후 사진 14장", page.evaluate("() => S.photos.length") == 14)
            check("업로드한 앨범으로 이동", page.evaluate("() => S.album") == "가족여행", page.evaluate("() => S.album"))
            page.click("#chips .chip:nth-child(1)")
            page.wait_for_function("() => document.querySelectorAll('#gallery .card').length === 14")
            check("전체에서 14장 표시", page.eval_on_selector_all("#gallery .card", "e => e.length") == 14)
            check("업로드 요청 2건", len(mock2.uploaded) == 2, len(mock2.uploaded))
            check("업로드 앨범 지정", all(u.get("album") == "가족여행" for u in mock2.uploaded))
            check("업로드 이미지(jpeg)로 변환", all(str(u.get("mimeType")).startswith("image/") for u in mock2.uploaded))
            page.screenshot(path=os.path.join(SHOTS, "photo-app-mobile-admin.png"))

            page.click("#gallery .card:nth-child(1)")
            page.wait_for_selector("#lb.show")
            page.wait_for_function("() => document.getElementById('lbImg').classList.contains('ready')")
            check("삭제 버튼 보임", page.eval_on_selector("#lbDelete", "e => !e.hidden"))
            page.on("dialog", lambda dlg: dlg.accept())
            page.click("#lbDelete")
            page.wait_for_function("() => document.querySelectorAll('#gallery .card').length === 13", timeout=8000)
            check("삭제 후 13장", page.eval_on_selector_all("#gallery .card", "e => e.length") == 13)
            check("삭제 요청 전달", len(mock2.deleted) == 1, mock2.deleted)
            page.keyboard.press("Escape")

            check("모바일 콘솔 오류 0", len(errors) == 0, errors)
            check("모바일 페이지 오류 0", len(page_errors) == 0, page_errors)
            ctx.close()

            # ── 3. 열람 비밀번호 ──
            print("[3] 열람 비밀번호(잠금)")
            photos3 = make_photos(6)
            mock3 = Mock(photos3, album_counts(photos3), locked=True)
            ctx, page, errors, page_errors, failed = new_page(browser, mock3, mobile=True)
            page.wait_for_selector("#lockScreen.show")
            check("잠금 화면 표시", True)
            page.screenshot(path=os.path.join(SHOTS, "photo-app-mobile-lock.png"))
            page.fill("#lockPin", "0000")
            page.click("#lockGo")
            page.wait_for_function("() => document.getElementById('lockMsg').textContent.length > 0")
            check("잠금 틀린 비밀번호", "맞지 않" in page.inner_text("#lockMsg"), page.inner_text("#lockMsg"))
            page.fill("#lockPin", "2580")
            page.click("#lockGo")
            page.wait_for_function("() => document.querySelectorAll('#gallery .card').length === 6")
            check("잠금 해제 후 6장", page.eval_on_selector_all("#gallery .card", "e => e.length") == 6)
            check("잠금 콘솔 오류 0", len(errors) == 0, errors)
            ctx.close()

            # ── 4. 빈 갤러리 ──
            print("[4] 빈 갤러리")
            mock4 = Mock([], {})
            ctx, page, errors, page_errors, failed = new_page(browser, mock4, mobile=True)
            page.wait_for_selector("#state:not([hidden])")
            check("빈 상태 문구", "아직 사진이 없어요" in page.inner_text("#stateTitle"), page.inner_text("#stateTitle"))
            check("빈 상태 사진 0장", "사진 0장" in page.inner_text("#subTitle"), page.inner_text("#subTitle"))
            check("빈 상태에선 검색 숨김", page.eval_on_selector("#bar", "e => getComputedStyle(e).display === 'none'"))
            page.screenshot(path=os.path.join(SHOTS, "photo-app-mobile-empty.png"))
            check("빈 상태 콘솔 오류 0", len(errors) == 0, errors)
            ctx.close()

            # ── 5. 서버 오류 ──
            print("[5] 서버 오류 상태")
            def fail_route(route):
                route.fulfill(status=500, headers={"access-control-allow-origin": "*"}, body="boom")
            ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            page = ctx.new_page()
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.route(re.compile(r"^https://script\.google\.com/macros/s/.*"), fail_route)
            page.goto(BASE + "/index.html?url=" + urllib.parse.quote(FAKE_URL))
            page.wait_for_selector("#state:not([hidden])")
            check("오류 상태 문구", "불러오지 못했어요" in page.inner_text("#stateTitle"), page.inner_text("#stateTitle"))
            check("오류 상태에 다시 시도", page.is_visible("#stRetry"))
            check("오류 상태 상단 안내", "불러오지 못했어요" in page.inner_text("#subTitle"), page.inner_text("#subTitle"))
            ctx.close()

            # ── 6. 많은 사진(120장) — 지연 로딩 ──
            print("[6] 사진 120장 — 지연 로딩")
            many = []
            for i in range(120):
                many.append({"id": "M%d" % i, "name": "photo_%03d.jpg" % i, "album": "앨범%d" % (i % 4),
                             "date": "2026-%02d-%02dT10:00:00" % (1 + i % 12, 1 + i % 28),
                             "dateLabel": "2026.%02d.%02d" % (1 + i % 12, 1 + i % 28),
                             "mimeType": "image/jpeg", "size": 2048})
            mock6 = Mock(many, album_counts(many))
            Mock.img_calls = 0
            ctx, page, errors, page_errors, failed = new_page(browser, mock6, mobile=True)
            page.wait_for_function("() => document.querySelectorAll('#gallery .card').length === 120")
            page.wait_for_timeout(900)
            early = Mock.img_calls
            check("처음엔 화면 근처만 받음", 0 < early <= 30, early)
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1200)
            check("스크롤하면 더 받음", Mock.img_calls > early, (early, Mock.img_calls))
            last_ready = page.eval_on_selector_all("#gallery .card:last-child img.ready", "e => e.length")
            check("마지막 카드도 그림", last_ready == 1, last_ready)
            check("120장 콘솔 오류 0", len(errors) == 0, errors[:3])
            ctx.close()

            # ── 7. 사진 댓글 — 데스크톱(1280) ──
            print("[7] 사진 댓글 — 데스크톱")
            photos7 = make_photos()
            mock7 = Mock(photos7, album_counts(photos7))
            mock7.comments["P1"] = [
                {"id": "S1", "author": "보은", "text": "가족여행 사진 정말 좋네요",
                 "createdAt": "2026-11-23T10:00:00", "dateLabel": "2026.11.23 10:00"},
                {"id": "S2", "author": "연수", "text": "다음에 또 가자!",
                 "createdAt": "2026-11-23T11:00:00", "dateLabel": "2026.11.23 11:00"},
            ]
            ctx, page, errors, page_errors, failed = new_page(browser, mock7)
            page.wait_for_function("() => document.querySelectorAll('#gallery .card').length === 12")
            page.wait_for_timeout(500)
            check("카드에 댓글 배지 💬 2",
                  page.eval_on_selector("#gallery .card:nth-child(1) .cm-badge", "e => e.textContent.trim()") == "💬 2",
                  page.eval_on_selector_all("#gallery .card .cm-badge", "els => els.map(e => e.textContent.trim())"))
            check("댓글 없는 카드엔 배지 없음",
                  page.eval_on_selector_all("#gallery .card .cm-badge", "els => els.length") == 1)
            page.mouse.move(4, 4)
            page.wait_for_timeout(200)
            page.screenshot(path=os.path.join(SHOTS, "photo-app-desktop-comments-grid.png"))

            page.click("#gallery .card:nth-child(1)")
            page.wait_for_selector("#lb.show")
            page.wait_for_function("() => document.querySelectorAll('#cmList .cm-item').length === 2")
            check("댓글 목록 불러옴", page.inner_text("#cmCountNum") == "2", page.inner_text("#cmCountNum"))
            first_cm = page.eval_on_selector("#cmList .cm-item:first-child",
                                            "e => ({name: e.querySelector('b').textContent, text: e.querySelector('p').textContent})")
            check("댓글 작성자·내용·순서", first_cm["name"] == "보은" and first_cm["text"] == "가족여행 사진 정말 좋네요", first_cm)
            b_stage, b_side = box_of(page, "#lbStage"), box_of(page, "#lbSide")
            check("데스크톱은 오른쪽 댓글 패널", b_side["x"] >= b_stage["x"] + b_stage["w"] - 2, (b_stage, b_side))
            check("관리자 아니면 🗑 숨김",
                  page.eval_on_selector("#cmList .cm-item:first-child .cm-del", "e => getComputedStyle(e).display === 'none'"))
            page.wait_for_timeout(500)
            page.screenshot(path=os.path.join(SHOTS, "photo-app-desktop-comments.png"))

            page.fill("#cmName", "진홍")
            page.fill("#cmText", "잘 보고 갑니다")
            check("글자 수 표시", page.inner_text("#cmCount") == "8/300", page.inner_text("#cmCount"))
            page.click("#cmSend")
            page.wait_for_function("() => document.querySelectorAll('#cmList .cm-item').length === 3")
            check("댓글 즉시 반영", page.inner_text("#cmList .cm-item:last-child p") == "잘 보고 갑니다",
                  page.inner_text("#cmList .cm-item:last-child p"))
            check("댓글 수 갱신", page.inner_text("#cmCountNum") == "3", page.inner_text("#cmCountNum"))
            check("카드 배지 갱신(💬 3)",
                  page.eval_on_selector("#gallery .card:nth-child(1) .cm-badge", "e => e.textContent.trim()") == "💬 3",
                  page.eval_on_selector("#gallery .card:nth-child(1) .cm-badge", "e => e.textContent"))
            check("작성 요청 내용",
                  mock7.comments_added and mock7.comments_added[-1].get("author") == "진홍"
                  and mock7.comments_added[-1].get("photoId") == "P1", mock7.comments_added[-1:])
            check("입력창 비워짐", page.input_value("#cmText") == "")
            check("이름 기억(localStorage)", page.evaluate("() => localStorage.getItem('hg_cm_name')") == "진홍")

            before = len(mock7.comments_added)
            page.fill("#cmText", "   ")
            page.click("#cmSend")
            page.wait_for_timeout(350)
            check("빈 댓글은 요청하지 않음", len(mock7.comments_added) == before, len(mock7.comments_added))
            check("빈 댓글 안내", "댓글 내용을 입력" in page.inner_text("#toast"), page.inner_text("#toast"))

            page.fill("#cmName", "<script>x</script>")
            page.fill("#cmText", "<img src=x onerror=window.__xss=1>")
            page.click("#cmSend")
            page.wait_for_function("() => document.querySelectorAll('#cmList .cm-item').length === 4")
            xss = page.eval_on_selector("#cmList .cm-item:last-child",
                                        "e => ({name: e.querySelector('b').textContent, text: e.querySelector('p').textContent, nodes: e.querySelectorAll('img,script,b img').length})")
            check("XSS 이름 평문 렌더", xss["name"] == "<script>x</script>", xss)
            check("XSS 내용 평문 렌더", xss["text"] == "<img src=x onerror=window.__xss=1>", xss)
            check("XSS가 요소로 실행되지 않음", xss["nodes"] == 0 and page.evaluate("() => window.__xss === undefined"), xss)

            page.click("#lbNext")
            page.wait_for_function("() => { const e = document.querySelector('#cmList .cm-empty'); return !!e && e.textContent.indexOf('댓글이 없어요') >= 0; }")
            check("다른 사진은 빈 댓글", "아직 댓글이 없어요" in page.inner_text("#cmList"), page.inner_text("#cmList"))
            page.click("#lbPrev")
            page.wait_for_function("() => document.querySelectorAll('#cmList .cm-item').length === 4")
            check("돌아오면 원래 사진 댓글", page.inner_text("#lbCount").startswith("1 /"), page.inner_text("#lbCount"))

            page.click("#cmText")
            page.keyboard.press("ArrowRight")
            page.wait_for_timeout(250)
            check("댓글 입력 중 화살표는 사진 안 넘김", page.inner_text("#lbCount").startswith("1 /"), page.inner_text("#lbCount"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)

            page.click("#btnAdmin")
            page.wait_for_selector("#ovPin.show")
            page.fill("#pinInput", "2580")
            page.click("#pinOk")
            page.wait_for_selector("#fab.show")
            page.click("#gallery .card:nth-child(1)")
            page.wait_for_selector("#lb.show")
            page.wait_for_function("() => document.querySelectorAll('#cmList .cm-item').length === 4")
            check("관리자면 🗑 보임",
                  page.eval_on_selector("#cmList .cm-item:first-child .cm-del", "e => getComputedStyle(e).display !== 'none'"))
            page.on("dialog", lambda dlg: dlg.accept())
            page.click("#cmList .cm-item:first-child .cm-del")
            page.wait_for_function("() => document.querySelectorAll('#cmList .cm-item').length === 3")
            check("관리자 PIN 으로 댓글 삭제", mock7.deleted_comments == ["S1"], mock7.deleted_comments)
            check("삭제된 댓글 사라짐", "보은" not in page.inner_text("#cmList"), page.inner_text("#cmList")[:120])
            check("삭제 후 카드 배지 3",
                  page.eval_on_selector("#gallery .card:nth-child(1) .cm-badge", "e => e.textContent.trim()") == "💬 3")
            page.wait_for_timeout(300)
            page.screenshot(path=os.path.join(SHOTS, "photo-app-desktop-comments-admin.png"))
            check("댓글 콘솔 오류 0", len(errors) == 0, errors)
            check("댓글 페이지 오류 0", len(page_errors) == 0, page_errors)
            ctx.close()

            # ── 8. 사진 댓글 — 모바일(390) ──
            print("[8] 사진 댓글 — 모바일")
            photos8 = make_photos(6)
            mock8 = Mock(photos8, album_counts(photos8))
            mock8.comments["P1"] = [{"id": "M1", "author": "보은", "text": "모바일에서도 잘 보이네요",
                                     "createdAt": "2026-11-23T10:00:00", "dateLabel": "2026.11.23 10:00"}]
            ctx, page, errors, page_errors, failed = new_page(browser, mock8, mobile=True)
            page.wait_for_function("() => document.querySelectorAll('#gallery .card').length === 6")
            page.wait_for_timeout(400)
            page.click("#gallery .card:nth-child(1)")
            page.wait_for_selector("#lb.show")
            page.wait_for_function("() => document.querySelectorAll('#cmList .cm-item').length === 1")
            m_stage, m_side = box_of(page, "#lbStage"), box_of(page, "#lbSide")
            check("모바일은 사진 아래 댓글 패널", m_side["y"] >= m_stage["y"] + m_stage["h"] - 2, (m_stage, m_side))
            check("모바일 댓글 패널 화면 안", m_side["h"] > 90 and m_side["y"] + m_side["h"] <= 846, m_side)
            check("모바일 댓글 내용", "모바일에서도 잘 보이네요" in page.inner_text("#cmList"))
            page.fill("#cmText", "휴대폰에서 남긴 댓글 😊")
            page.click("#cmSend")
            page.wait_for_function("() => document.querySelectorAll('#cmList .cm-item').length === 2")
            check("모바일 댓글 등록", page.inner_text("#cmCountNum") == "2", page.inner_text("#cmCountNum"))
            check("이모지 그대로 표시", "휴대폰에서 남긴 댓글 😊" in page.inner_text("#cmList"), page.inner_text("#cmList"))
            check("모바일 카드 배지 갱신",
                  page.eval_on_selector("#gallery .card:nth-child(1) .cm-badge", "e => e.textContent.trim()") == "💬 2",
                  page.eval_on_selector("#gallery .card:nth-child(1) .cm-badge", "e => e.textContent"))
            page.wait_for_timeout(400)
            page.screenshot(path=os.path.join(SHOTS, "photo-app-mobile-comments.png"))
            check("모바일 댓글 콘솔 오류 0", len(errors) == 0, errors)
            check("모바일 댓글 페이지 오류 0", len(page_errors) == 0, page_errors)
            ctx.close()

            # ── 9. 구형 스크립트(댓글 미지원) ──
            print("[9] 구형 스크립트 — 댓글 안내")
            photos9 = make_photos(6)
            mock9 = Mock(photos9, album_counts(photos9), old_script=True)
            ctx, page, errors, page_errors, failed = new_page(browser, mock9, mobile=True)
            page.wait_for_function("() => document.querySelectorAll('#gallery .card').length === 6")
            check("구형 스크립트엔 배지 없음", page.eval_on_selector_all("#gallery .card .cm-badge", "els => els.length") == 0)
            page.click("#gallery .card:nth-child(1)")
            page.wait_for_selector("#lb.show")
            page.wait_for_function("() => document.getElementById('cmNote').classList.contains('show')")
            check("구형 스크립트 안내 문구", "새 스크립트 배포 후" in page.inner_text("#cmNote"), page.inner_text("#cmNote"))
            check("구형 스크립트에선 등록 잠김", page.eval_on_selector("#cmSend", "e => e.disabled"))
            check("사진은 정상 표시", page.eval_on_selector("#lbImg", "e => e.classList.contains('ready')"))
            check("구형 스크립트 콘솔 오류 0", len(errors) == 0, errors)
            page.wait_for_timeout(200)
            page.screenshot(path=os.path.join(SHOTS, "photo-app-mobile-comments-old-script.png"))
            ctx.close()

            browser.close()
    finally:
        httpd.shutdown()

    print()
    print("%d개 확인" % checks)
    if failures:
        print("실패 %d건: %s" % (len(failures), ", ".join(failures)))
        return 1
    print("화면 테스트 모두 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
