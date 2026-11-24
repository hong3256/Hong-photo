#!/usr/bin/env python3
"""downloads/photo-apps-script.txt (Code.gs) 로직 검증.

구글 서비스는 최소한으로 흉내 내고(DriveApp·ContentService·Utilities·UrlFetchApp…)
doGet / doPost 를 실제로 실행해 ping·list·img·upload·delete·PIN·잠금을 확인한다.
개인 사진·폴더 ID는 쓰지 않고, 가짜 드라이브를 메모리에 만든다.
"""
import json
import os
import re
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GS = os.path.join(os.path.dirname(HERE), "downloads", "photo-apps-script.txt")

HARNESS = r"""
(args) => {
  const code = args.code;
  const mode = args.mode;
  let THUMB_FAIL = false;

  const b64 = (bytes) => { let s = ''; for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i] & 255); return btoa(s); };
  const unb64 = (str) => { const s = atob(str); const a = []; for (let i = 0; i < s.length; i++) a.push(s.charCodeAt(i)); return a; };
  const mkBytes = (n, seed) => { const a = []; for (let i = 0; i < n; i++) a.push((i * 31 + seed * 17) % 256); return a; };
  const pad = (n) => (n < 10 ? '0' + n : '' + n);
  const dt = (s) => new Date(s);
  const THUMB_BYTES = mkBytes(64, 9);

  /* ── 가짜 드라이브 ── */
  const FID = /var FOLDER_ID\s*=\s*'([^']+)'/.exec(code)[1];
  const OUT_ID = 'OUTSIDE_FOLDER';
  const store = { folders: {}, files: {}, seq: 0 };

  function Folder(id, name, parent) { this.id = id; this.name = name; this.parent = parent || null; }
  Folder.prototype.getId = function () { return this.id; };
  Folder.prototype.getName = function () { return this.name; };
  Folder.prototype.getParents = function () { return iter(this.parent ? [this.parent] : []); };
  Folder.prototype.getFiles = function () {
    const self = this;
    return iter(Object.values(store.files).filter(f => f.parent === self && !f.trashed));
  };
  Folder.prototype.getFolders = function () {
    const self = this;
    return iter(Object.values(store.folders).filter(f => f.parent === self));
  };
  Folder.prototype.createFolder = function (name) {
    const f = new Folder('NEWF_' + (++store.seq), name, this);
    store.folders[f.id] = f;
    return f;
  };
  Folder.prototype.createFile = function (blob) {
    const id = 'NEW_' + (++store.seq);
    return addFile(id, blob.getName(), blob.getContentType(), this, '2026-11-24T09:00:00Z', blob.getBytes().length, blob.getBytes());
  };

  function File(o) { Object.assign(this, o); }
  File.prototype.getId = function () { return this.id; };
  File.prototype.getName = function () { return this.name; };
  File.prototype.getMimeType = function () { return this.mime; };
  File.prototype.getSize = function () { return this.size; };
  File.prototype.getLastUpdated = function () { return dt(this.updated); };
  File.prototype.getDateCreated = function () { return dt(this.created || this.updated); };
  File.prototype.getParents = function () { return iter([this.parent]); };
  File.prototype.getBlob = function () {
    const self = this;
    return { getBytes: () => self.bytes.slice(), getContentType: () => self.mime, getName: () => self.name };
  };
  File.prototype.setTrashed = function (v) { this.trashed = !!v; };

  function addFile(id, name, mime, parent, updated, size, bytes) {
    const f = new File({ id, name, mime, parent, updated, size, bytes: bytes || mkBytes(40, 3), trashed: false });
    store.files[id] = f;
    return f;
  }
  function iter(arr) { let i = 0; return { hasNext: () => i < arr.length, next: () => arr[i++] }; }

  const root = new Folder(FID, '진홍 포토 갤러리');
  store.folders[FID] = root;
  const albumA = root.createFolder('가족여행');
  root.createFolder('빈앨범');
  const outside = new Folder(OUT_ID, '다른 폴더');
  store.folders[OUT_ID] = outside;

  addFile('F1', 'IMG_0001.jpg', 'image/jpeg', root, '2026-11-20T10:00:00Z', 120, mkBytes(120, 1));
  addFile('F2', 'IMG_0002.jpg', 'image/jpeg', root, '2026-11-18T08:30:00Z', 90, mkBytes(90, 2));
  addFile('F3', 'kakao.png', 'image/png', albumA, '2026-11-22T09:00:00Z', 80, mkBytes(80, 3));
  addFile('F4', 'IMG_0004.jpg', 'image/jpeg', albumA, '2026-11-15T21:10:00Z', 70, mkBytes(70, 4));
  addFile('F5', 'doc.pdf', 'application/pdf', root, '2026-11-21T09:00:00Z', 30);
  addFile('F6', 'private.jpg', 'image/jpeg', outside, '2026-11-23T09:00:00Z', 50, mkBytes(50, 6));
  addFile('F7', 'BIG.jpg', 'image/jpeg', root, '2026-11-10T09:00:00Z', 30 * 1024 * 1024, mkBytes(10, 7));

  /* ── 가짜 구글 서비스 ── */
  const DriveApp = {
    getFolderById(id) { const f = store.folders[id]; if (!f) throw new Error('not found'); return f; },
    getFileById(id) { const f = store.files[id]; if (!f) throw new Error('not found'); return f; }
  };
  const ContentService = {
    MimeType: { JSON: 'application/json' },
    createTextOutput(text) {
      let mime = 'text/plain';
      return { getContent: () => text, getMimeType: () => mime, setMimeType(m) { mime = m; return this; } };
    }
  };
  const Utilities = {
    formatDate(d, tz, fmt) {
      const x = (d instanceof Date) ? d : new Date(d);
      return fmt.replace(/'/g, '').replace('yyyy', String(x.getFullYear())).replace('MM', pad(x.getMonth() + 1))
        .replace('dd', pad(x.getDate())).replace('HH', pad(x.getHours()))
        .replace('mm', pad(x.getMinutes())).replace('ss', pad(x.getSeconds()));
    },
    base64Encode(b) { return b64(Array.from(b)); },
    base64EncodeWebSafe(b) { return b64(Array.from(b)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); },
    base64Decode(s) { return unb64(s); },
    newBlob(bytes, mime, name) {
      return { getBytes: () => Array.from(bytes), getContentType: () => mime, getName: () => name };
    },
    getUuid() { return 'uuid-' + (++store.seq); },
    computeHmacSha256Signature(text, secret) {
      let h1 = 0x12345678;
      const str = String(text) + '|' + String(secret);
      for (let i = 0; i < str.length; i++) h1 = (h1 * 131 + str.charCodeAt(i)) >>> 0;
      const out = [];
      for (let i = 0; i < 32; i++) { h1 = (h1 * 1103515245 + 12345) >>> 0; out.push(h1 & 255); }
      return out;
    }
  };
  const ScriptApp = { getOAuthToken() { return 'fake-oauth-token'; } };
  const UrlFetchApp = {
    fetch(url) {
      if (url.indexOf('googleapis.com/drive/v3/files/') >= 0) {
        if (THUMB_FAIL) return { getResponseCode: () => 404, getContentText: () => '{"error":{}}', getBlob: () => null };
        const id = decodeURIComponent(url.split('/files/')[1].split('?')[0]);
        return {
          getResponseCode: () => 200,
          getContentText: () => JSON.stringify({ thumbnailLink: 'https://lh3.test/t/' + id + '=s220' }),
          getBlob: () => null
        };
      }
      if (url.indexOf('lh3.test') >= 0) {
        if (THUMB_FAIL) return { getResponseCode: () => 404, getContentText: () => '', getBlob: () => null };
        return {
          getResponseCode: () => 200, getContentText: () => '',
          getBlob: () => ({ getBytes: () => THUMB_BYTES.slice(), getContentType: () => 'image/jpeg', getName: () => 'thumb.jpg' })
        };
      }
      return { getResponseCode: () => 404, getContentText: () => '', getBlob: () => null };
    }
  };
  const cacheMap = {};
  const CacheService = { getScriptCache() { return { get: k => cacheMap[k] || null, put: (k, v) => { cacheMap[k] = v; } }; } };
  const props = {};
  const PropertiesService = {
    getScriptProperties() {
      return { getProperty: k => (k in props ? props[k] : null), setProperty: (k, v) => { props[k] = v; } };
    }
  };
  const LockService = { getScriptLock() { return { waitLock() { }, releaseLock() { } }; } };

  const api = new Function(
    'DriveApp', 'ContentService', 'Utilities', 'UrlFetchApp', 'ScriptApp', 'CacheService', 'PropertiesService', 'LockService',
    code + '\nreturn {doGet: doGet, doPost: doPost};'
  )(DriveApp, ContentService, Utilities, UrlFetchApp, ScriptApp, CacheService, PropertiesService, LockService);

  const call = (fn, ev) => { const out = api[fn](ev); return { mime: out.getMimeType(), body: JSON.parse(out.getContent()) }; };
  const GET = (p) => call('doGet', { parameter: p || {} }).body;
  const POST = (o) => call('doPost', { postData: { contents: JSON.stringify(o) } }).body;

  const out = { b64: { f1: b64(store.files.F1.bytes), thumb: b64(THUMB_BYTES), up: b64(mkBytes(33, 5)), rootUp: b64(mkBytes(15, 6)) } };
  const R = out.R = {};

  if (mode === 'base') {
    R.ping = GET({ action: 'ping' });
    R.list = GET({ action: 'list' });

    R.imgFull = GET({ action: 'img', id: 'F1', size: 'full' });
    R.imgThumb = GET({ action: 'img', id: 'F1', size: 'thumb' });
    THUMB_FAIL = true;
    R.imgThumbFallback = GET({ action: 'img', id: 'F1', size: 'thumb' });
    R.imgBigTooLarge = GET({ action: 'img', id: 'F7', size: 'full' });
    THUMB_FAIL = false;
    R.imgBigResized = GET({ action: 'img', id: 'F7', size: 'full' });

    R.imgOutside = GET({ action: 'img', id: 'F6', size: 'full' });
    R.imgMissing = GET({ action: 'img', id: 'NOPE', size: 'full' });
    R.imgPdf = GET({ action: 'img', id: 'F5', size: 'full' });
    R.badAction = GET({ action: 'zzz' });

    R.uploadNoPin = POST({ action: 'upload', pin: '1111', filename: 'a.jpg', mimeType: 'image/jpeg', data: b64(mkBytes(20, 1)) });
    R.upload = POST({ action: 'upload', pin: '2580', filename: '새 사진', mimeType: 'image/png', data: b64(mkBytes(33, 5)), album: '새앨범' });
    R.uploadRoot = POST({ action: 'upload', pin: '2580', filename: 'root.jpg', mimeType: 'image/jpeg', data: b64(mkBytes(15, 6)), album: '' });
    R.uploadBadMime = POST({ action: 'upload', pin: '2580', filename: 'a.txt', mimeType: 'text/plain', data: b64(mkBytes(5, 1)) });
    R.uploadNoData = POST({ action: 'upload', pin: '2580', filename: 'a.jpg', mimeType: 'image/jpeg', data: '' });
    R.list2 = GET({ action: 'list' });

    R.authBad = POST({ action: 'auth', pin: '9999' });
    R.authOk = POST({ action: 'auth', pin: '2580' });

    R.deleteNoPin = POST({ action: 'delete', pin: '1111', id: 'F2' });
    R.deleteOutside = POST({ action: 'delete', pin: '2580', id: 'F6' });
    R.deleteMissing = POST({ action: 'delete', pin: '2580', id: 'NOPE' });
    R.delete = POST({ action: 'delete', pin: '2580', id: 'F2' });
    R.list3 = GET({ action: 'list' });
    R.badJson = call('doPost', { postData: { contents: '{oops' } }).body;

    out.trashedF2 = !!store.files.F2.trashed;
    out.newFileParent = (Object.values(store.folders).filter(f => f.name === '새앨범')[0] || {}).name || null;
    return out;
  }

  if (mode === 'lock') {
    R.ping = GET({ action: 'ping' });
    R.listNoToken = GET({ action: 'list' });
    R.listBadToken = GET({ action: 'list', token: 'abc.def' });
    R.loginBad = GET({ action: 'login', pin: '0000' });
    R.login = GET({ action: 'login', pin: '2580' });
    const tok = R.login.token || '';
    R.listWithToken = GET({ action: 'list', token: tok });
    R.imgWithToken = GET({ action: 'img', id: 'F1', size: 'thumb', token: tok });
    R.imgNoToken = GET({ action: 'img', id: 'F1', size: 'thumb' });
    R.tampered = GET({ action: 'list', token: tok.replace(/^\d+/, '1' + Date.now()) });
    R.postLogin = POST({ action: 'login', pin: '2580' });
    return out;
  }
  return out;
}
"""


def load_code(mode):
    with open(GS, encoding="utf-8") as f:
        code = f.read()
    assert re.search(r"var ADMIN_PIN\s*=\s*'[^']*';", code)
    code = re.sub(r"(var ADMIN_PIN\s*=\s*)'[^']*';", r"\1'2580';", code, count=1)
    if mode == "lock":
        assert "var VIEW_PIN   = '';" in code
        code = code.replace("var VIEW_PIN   = '';", "var VIEW_PIN   = '2580';")
    return code


def main():
    failures = []

    def check(name, cond, detail=None):
        if cond:
            print("  ✓", name)
        else:
            print("  ✗", name, json.dumps(detail, ensure_ascii=False)[:300] if detail is not None else "")
            failures.append(name)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto("about:blank")

        print("[1] 공개 갤러리 (VIEW_PIN='')")
        out = page.evaluate(HARNESS, {"code": load_code("base"), "mode": "base"})
        R = out["R"]
        B = out["b64"]

        ping = R["ping"]
        check("ping 폴더명", ping.get("name") == "진홍 포토 갤러리", ping)
        check("ping 사진 5장(이미지·갤러리 안만)", ping.get("photoCount") == 5, ping)
        check("ping 앨범 1개(사진 있는 폴더만)",
              ping.get("albumCount") == 1 and ping["albums"][0]["name"] == "가족여행", ping.get("albums"))
        check("ping 잠금 없음", ping.get("locked") is False, ping)

        lst = R["list"]
        check("list 최신순 정렬", [p["id"] for p in lst["photos"]] == ["F3", "F1", "F2", "F4", "F7"],
              [p["id"] for p in lst.get("photos", [])])
        check("list 전체 수", lst.get("total") == 5, lst.get("total"))
        names = [p["album"] + ":" + p["name"] for p in lst["photos"]]
        check("list 앨범 표시", "가족여행:kakao.png" in names and ":IMG_0001.jpg" in names, names)
        check("list 앨범 개수", lst.get("albums") == [{"name": "가족여행", "count": 2}], lst.get("albums"))
        d0 = lst["photos"][0]["date"]
        check("list 날짜 형식", len(d0) == 19 and d0[4] == "-" and d0[10] == "T", d0)

        f = R["imgFull"]
        check("img 전체: data URI", f.get("ok") and f["data"].startswith("data:image/jpeg;base64,"), {k: f.get(k) for k in ("ok", "error")})
        check("img 전체: 원본 바이트 일치", f["data"].split(",")[1] == B["f1"])
        t = R["imgThumb"]
        check("img 썸네일: 썸네일 바이트", t.get("ok") and t["data"].split(",")[1] == B["thumb"], {k: t.get(k) for k in ("ok", "error")})
        fb = R["imgThumbFallback"]
        check("img 썸네일 실패 시 원본 대체", fb.get("ok") and fb["data"].split(",")[1] == B["f1"], {k: fb.get(k) for k in ("ok", "error")})
        check("img 25MB 초과+썸네일 실패 → TOO_LARGE", R["imgBigTooLarge"].get("error") == "TOO_LARGE", R["imgBigTooLarge"])
        big = R["imgBigResized"]
        check("img 큰 원본 → 축소본(resized)", big.get("ok") and big.get("resized") is True, {k: big.get(k) for k in ("ok", "error", "resized")})

        check("img 갤러리 밖 파일 거부", R["imgOutside"].get("error") == "FORBIDDEN", R["imgOutside"])
        check("img 없는 파일", R["imgMissing"].get("error") == "NOT_FOUND", R["imgMissing"])
        check("img PDF 거부", R["imgPdf"].get("error") == "NOT_IMAGE", R["imgPdf"])
        check("알 수 없는 action", R["badAction"].get("error") == "BAD_REQUEST", R["badAction"])

        check("upload 잘못된 PIN", R["uploadNoPin"].get("error") == "BAD_PIN", R["uploadNoPin"])
        check("upload 성공·앨범", R["upload"].get("ok") is True and R["upload"].get("album") == "새앨범", R["upload"])
        check("upload 확장자 보정(png)", str(R["upload"].get("name", "")).endswith(".png"), R["upload"].get("name"))
        check("upload 앨범 없음", R["uploadRoot"].get("ok") is True and R["uploadRoot"].get("album") == "", R["uploadRoot"])
        check("upload 이미지 아님 거부", R["uploadBadMime"].get("error") == "NOT_IMAGE", R["uploadBadMime"])
        check("upload 데이터 없음", R["uploadNoData"].get("error") == "BAD_REQUEST", R["uploadNoData"])

        l2 = R["list2"]
        check("업로드 후 7장", l2.get("total") == 7, l2.get("total"))
        check("업로드 후 새앨범 1장", {"name": "새앨범", "count": 1} in (l2.get("albums") or []), l2.get("albums"))

        check("auth 잘못된 PIN", R["authBad"].get("error") == "BAD_PIN", R["authBad"])
        check("auth 성공", R["authOk"].get("ok") is True and R["authOk"].get("admin") is True, R["authOk"])

        check("delete 잘못된 PIN", R["deleteNoPin"].get("error") == "BAD_PIN", R["deleteNoPin"])
        check("delete 갤러리 밖 파일 거부", R["deleteOutside"].get("error") == "FORBIDDEN", R["deleteOutside"])
        check("delete 없는 파일", R["deleteMissing"].get("error") == "NOT_FOUND", R["deleteMissing"])
        check("delete 성공(휴지통)", R["delete"].get("ok") is True and R["delete"].get("trashed") is True, R["delete"])
        l3 = R["list3"]
        check("삭제 후 6장·F2 없음", l3.get("total") == 6 and "F2" not in [p["id"] for p in l3["photos"]] and out["trashedF2"],
              {"total": l3.get("total"), "trashed": out["trashedF2"]})
        check("깨진 JSON", R["badJson"].get("error") == "BAD_REQUEST", R["badJson"])

        print("[2] 열람 비밀번호 (VIEW_PIN='2580')")
        out2 = page.evaluate(HARNESS, {"code": load_code("lock"), "mode": "lock"})
        L = out2["R"]
        check("ping 잠금 표시", L["ping"].get("locked") is True, L["ping"])
        check("토큰 없이 list 거부", L["listNoToken"].get("error") == "LOCKED", L["listNoToken"])
        check("엉터리 토큰 거부", L["listBadToken"].get("error") == "LOCKED", L["listBadToken"])
        check("로그인 잘못된 PIN", L["loginBad"].get("error") == "BAD_PIN", L["loginBad"])
        tok = L["login"].get("token") or ""
        check("로그인 성공·토큰 발급", L["login"].get("ok") is True and "." in tok, L["login"])
        check("토큰으로 list 성공", L["listWithToken"].get("ok") is True and L["listWithToken"].get("total") == 5, L["listWithToken"])
        check("토큰으로 img 성공", L["imgWithToken"].get("ok") is True, L["imgWithToken"])
        check("토큰 없이 img 거부", L["imgNoToken"].get("error") == "LOCKED", L["imgNoToken"])
        check("변조 토큰 거부", L["tampered"].get("error") == "LOCKED", L["tampered"])
        check("POST 로그인 성공", L["postLogin"].get("ok") is True, L["postLogin"])

        browser.close()

    print()
    if failures:
        print("실패 %d건: %s" % (len(failures), ", ".join(failures)))
        return 1
    print("Apps Script 로직 테스트 모두 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
