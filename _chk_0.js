
		// LVGL-UI-STUDIO:跨源 iframe → config(cscript/design)與 do-str 走 postMessage。
		// 主頁面(localhost ↔ 127.0.0.1)與本 iframe 跨源,卡死只影響本 iframe。
		var _simConfig = null;
		var _simConfigWaiters = [];
		function _simWaitConfig() {
			if (_simConfig) return Promise.resolve();
			return new Promise(function (resolve) { _simConfigWaiters.push(resolve); });
		}
		function _simAck() {
			try { window.parent.postMessage({ type: "sim-ack" }, "*"); } catch (e) {}
		}
		window.addEventListener("message", function (e) {
			var d = e.data;
			if (!d || typeof d !== "object") return;
			if (d.type === "sim-config") {
				_simConfig = d;
				for (var i = 0; i < _simConfigWaiters.length; i++) _simConfigWaiters[i]();
				_simConfigWaiters = [];
			} else if (d.type === "sim-do-str") {
				if (d.code) {
					try { mp_js_do_str(d.code); } catch (e2) {}
				}
				_simAck();
			}
		});
		var prevQuery = document.querySelector;
		document.querySelector = function(selector) {
			if(selector == "#canvas")
				return document.getElementById('simcanvas');
			else
				return prevQuery(selector);
		}
        var mp_js_stdout;
        var currentSleepingResolve = null;
        window.do_sleep_with_intr = function(ms, cb) {
            var i = setTimeout(() => {
                currentSleepingResolve = null;
                cb(0);
            }, ms);
            currentSleepingResolve = function() {
                clearTimeout(i);
                currentSleepingResolve = null;
                cb(1);
            };
        }
		/*Write text to the terminal(跨源:postMessage 給主頁面) */
		function sendText(text) {
			try { window.parent.postMessage({ type: "micropython-print", text: text }, "*"); } catch (e) {}
		}
		function reloadScript(target_script) {
			var url = [location.protocol, '//', location.host, location.pathname].join('');
			window.location.replace(url + "?env=dev&script=" + target_script);
		}
		async function decompressScript(compressed) {
            var lvBindingsCommitHash = (_simConfig && _simConfig.commit) || "";
			var script = LZString.decompressFromEncodedURIComponent(compressed);
            console.warn("running init script");
            await mp_js_do_str(`
import imp, usys as sys
sys.path.append('/sim/driver/js')
sys.path.append('/sim/lib')
            `);
            console.warn("running main script");
			await mp_js_do_str(script);
		}

		function getSearchArg(argname) {
			/* Run custom script if passed */
			var custom = undefined;
			try {
				custom = new URL(window.location.href).searchParams.get(argname);
			} catch (e) {
				console.log(e + ": URL seems to be unsupported");
			}
			return custom;
		}

		Module.canvas = (function() {
			var canvas = document.getElementById('simcanvas');
			return canvas;
		})();

        var inputChars = [];
		/*Initialization function*/
		window.startRunning = async function() {
			// 跨源模式:等待主頁面送 config(cscript/design)
			await _simWaitConfig();
			/*Setup printing event handler*/

			mp_js_stdout = window.parent;
			if(mp_js_stdout === undefined || mp_js_stdout === null) {
				throw "Could not retrieve parent window";
			}

			var requestedMemoryStr = null;
			try { requestedMemoryStr = new URL(window.parent.location.href).searchParams.get("memory"); } catch (e) {}
			// 預設 4MB（原 1MB 對字體+圖示+LVGL 物件太緊，GC 頻繁暫停會造成卡死感）
			var requestedMemory = 4 * 1024 * 1024;
			if(requestedMemoryStr != null) {
				requestedMemoryStr = parseInt(requestedMemoryStr);
				if(!isNaN(requestedMemoryStr) && requestedMemoryStr > 0)
					requestedMemory = requestedMemoryStr;
			}
			/*Initialize MicroPython itself*/
			console.log("Loading with " + requestedMemory + " bytes of heap");
			mp_js_init(requestedMemory);

// --- BEGIN LVGL UI STUDIO: seed MEMFS with /sim driver&lib .py ---
            (function () {
              var simBase = location.href.substring(0, location.href.lastIndexOf('/'));
              if (!simBase.endsWith('/')) simBase = simBase + '/';
              // driver/lib 是靜態檔：先查 sessionStorage（跨 reload 免抓），再查 MEMFS
              // （同頁面重複執行免抓），都沒有才同步 XHR fetch。
              var CACHE_KEY = 'lvglsim:' + simBase + ':';
              function syncFetchText(url) {
                try {
                  var x = new XMLHttpRequest();
                  x.open('GET', url, false);
                  try { x.responseType = 'text'; } catch (e) {}
                  x.send(null);
                  if (x.status === 200 || x.status === 0) return x.responseText;
                } catch (e) {}
                return null;
              }
              function ensureDir(path) {
                var parts = path.split('/').filter(Boolean);
                var cur = '/';
                for (var i = 0; i < parts.length; i++) {
                  cur = cur + parts[i] + '/';
                  try { FS.mkdir(cur.replace(/\/$/, '')); } catch (e) { if (e && e.code !== 'EEXIST') { throw e; } }
                }
              }
              function writePy(vfsPath, url) {
                try { if (FS.analyzePath(vfsPath).exists) return true; } catch (e) {}
                var text = null;
                try { text = sessionStorage.getItem(CACHE_KEY + vfsPath); } catch (e) {}
                if (text == null) text = syncFetchText(url);
                if (text == null) return false;
                ensureDir(vfsPath.substring(0, vfsPath.lastIndexOf('/')));
                try { FS.createDataFile('/', vfsPath.substring(1), text, true, true); }
                catch (e) { if (e && e.code !== 'EEXIST') return false; }
                try { sessionStorage.setItem(CACHE_KEY + vfsPath, text); } catch (e) {}
                return true;
              }
              var files = [
                ['/sim/lib/display_driver.py',        simBase + 'lib/display_driver.py'],
                ['/sim/lib/display_driver_utils.py',  simBase + 'lib/display_driver_utils.py'],
                ['/sim/lib/fs_driver.py',             simBase + 'lib/fs_driver.py'],
                ['/sim/lib/lv_colors.py',             simBase + 'lib/lv_colors.py'],
                ['/sim/lib/lv_utils.py',              simBase + 'lib/lv_utils.py'],
                ['/sim/lib/tpcal.py',                 simBase + 'lib/tpcal.py'],
                ['/sim/lib/utils.py',                 simBase + 'lib/utils.py'],
                ['/sim/driver/js/lv_timer.py',        simBase + 'driver/js/lv_timer.py'],
              ];
              var ok = 0;
              for (var i = 0; i < files.length; i++) {
                if (writePy(files[i][0], files[i][1])) ok++;
              }
              window.__lvgl_sim_seed_ok = ok;
              console.log("[MEMFS] seeded " + ok + "/" + files.length + " driver/lib .py (sim base=" + simBase + ")");
              // 板端 ui_common 開 '/ui/lvgl/src/*.bin'（字體/圖示）。Python 端 urequests
              // 在 wasm 無 socket 抓不了，這裡用 JS 同步 XHR 從 dlib fetch 寫入 MEMFS。
              try { ensureDir('/ui/lvgl/src'); } catch (e) {}
              (function () {
                var designName = (_simConfig && _simConfig.design) || "";
                if (!designName) return;
                function syncFetchBin(url) {
                  // 同步 XHR 的 arraybuffer 在 iframe 內不可靠（status 200 但 response 空），
                  // 改用 wasm_file_api 同款的「latin1 字串 + charCodeAt」二進位讀法。
                  try {
                    var x = new XMLHttpRequest();
                    x.open('GET', url, false);
                    try { x.overrideMimeType('text/plain; charset=x-user-defined'); } catch (e) {}
                    x.send(null);
                    var txt = x.responseText || '';
                    var len = txt.length;
                    if (x.status === 200 && len > 0) {
                      var out = new Uint8Array(len);
                      for (var i = 0; i < len; i++) out[i] = txt.charCodeAt(i) & 0xff;
                      return { status: x.status, len: len, resp: out };
                    }
                    return { status: x.status, len: 0, resp: null };
                  } catch (e) {
                    return { status: -1, len: -1, err: String(e) };
                  }
                }
                function writeBin(vfsPath, data) {
                  ensureDir(vfsPath.substring(0, vfsPath.lastIndexOf('/')));
                  try { FS.unlink(vfsPath); } catch (e) {}
                  try {
                    FS.createDataFile('/', vfsPath.substring(1), new Uint8Array(data), true, true);
                    return true;
                  } catch (e) { return false; }
                }
                function binToB64(u8) {
                  var s = '';
                  for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
                  try { return btoa(s); } catch (e) { return null; }
                }
                function b64ToBin(b64) {
                  var s = atob(b64), out = new Uint8Array(s.length);
                  for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i) & 0xff;
                  return out;
                }
                var binNames = ['zh_hant_16.bin', 'icons_16.bin'];
                var srcCands = [
                  location.origin + '/dlib/' + designName + '/lvgl/ui/src/',
                  location.origin + '/dlib/' + designName + '/ui/src/',
                  location.origin + '/dlib/' + designName + '/src/',
                ];
                var binLog = ['design=' + designName];
                for (var bi = 0; bi < binNames.length; bi++) {
                  // 已寫入（同頁面重複執行）→ 跳過；sessionStorage 快取（跨 reload 免抓）
                  var vp = '/ui/lvgl/src/' + binNames[bi];
                  try { if (FS.analyzePath(vp).exists) { binLog.push(binNames[bi] + ' MEMFS'); continue; } } catch (e) {}
                  var cached = null;
                  try { cached = sessionStorage.getItem('lvglsim:' + designName + ':' + binNames[bi]); } catch (e) {}
                  if (cached != null && cached.length > 0) {
                    try {
                      var cdata = b64ToBin(cached);
                      if (writeBin(vp, cdata)) {
                        binLog.push(binNames[bi] + ' CACHE ' + cdata.length);
                        console.log("[bin] cached " + binNames[bi] + " (" + cdata.length + " bytes)");
                        continue;
                      }
                    } catch (e) {}
                  }
                  for (var si2 = 0; si2 < srcCands.length; si2++) {
                    var r = syncFetchBin(srcCands[si2] + binNames[bi]);
                    binLog.push(binNames[bi] + '[' + si2 + '] status=' + r.status + ' len=' + r.len + (r.err ? ' err=' + r.err : ''));
                    if (r.resp && writeBin(vp, r.resp)) {
                      binLog.push(binNames[bi] + ' WRITTEN ' + r.len);
                      console.log("[bin] seeded " + binNames[bi] + " (" + r.len + " bytes)");
                      try { sessionStorage.setItem('lvglsim:' + designName + ':' + binNames[bi], binToB64(r.resp)); } catch (e) {}
                      break;
                    }
                  }
                }
                try {
                  FS.writeFile('/__bin_log', binLog.join('\n') || 'none');
                } catch (e) {}
              })();

              // --- LVGL UI STUDIO: dlib ui .py 預載（加速 framework 啟動） ---
              // framework 的 Python urequests 在 wasm 走同步 bridge 很慢；JS 逐檔 XHR
              // 在隱藏 iframe 也慢（~280ms/請求）。改為一次請求 /api/design/simfiles
              // 拿全部 ui .py 內容，寫進 /_wsp/{design}/（含 src/、page/）再寫
              // .preloaded 標記 — Python 端見到標記就完全跳過 preload。
              (function () {
                var designName = (_simConfig && _simConfig.design) || "";
                if (!designName) return;
                var wspRoot = '/_wsp/' + designName;
                function fetchText(url) {
                  try {
                    var x = new XMLHttpRequest();
                    x.open('GET', url, false);
                    x.send(null);
                    if (x.status === 200) return x.responseText;
                  } catch (e) {}
                  return null;
                }
                try { ensureDir(wspRoot + '/src'); ensureDir(wspRoot + '/page'); } catch (e) {}
                var text = fetchText(location.origin + '/api/design/simfiles?design=' + encodeURIComponent(designName));
                var total = 0;
                if (text != null) {
                  try {
                    var data = JSON.parse(text);
                    if (data && data.ok && data.files) {
                      var keys = Object.keys(data.files);
                      for (var ki = 0; ki < keys.length; ki++) {
                        var rel = keys[ki];
                        var fname = rel.substring(rel.lastIndexOf('/') + 1);
                        var sub = rel.indexOf('/') >= 0 ? rel.substring(0, rel.lastIndexOf('/')) : '';
                        var dir = (sub === 'src' || sub === 'page') ? '/' + sub : '';
                        try { FS.writeFile(wspRoot + dir + '/' + fname, data.files[rel]); total++; }
                        catch (e) {}
                      }
                    }
                  } catch (e) {}
                }
                if (total > 0) { try { FS.writeFile(wspRoot + '/.preloaded', String(total)); } catch (e) {} }
                console.log("[wsp] preloaded " + total + " ui .py -> " + wspRoot);
              })();

              // --- wasm_file_api shim：firmware 把 display_driver 等 driver 當「online module」，
              // import 時走 wasm_file_open/exists 去抓檔（不查 MEMFS/sys.path）。自架沒有
              // ?script= 參數，相對路徑抓檔失敗 → ImportError。這裡覆寫兩個函式：先查 MEMFS
              // （seed 的 /sim/ 與 framework preload 的 /_wsp/），命中就回傳本地檔，否則走原邏輯。
              if (typeof window.wasm_file_open === 'function' && typeof FS !== 'undefined') {
                // MEMFS log（Python 端 open('/__shim_log') 可讀）:診斷 shim 是否被呼叫
                function shimLog(msg) {
                  try {
                    var prev = '';
                    try { prev = FS.readFile('/__shim_log', { encoding: 'utf8' }); } catch (e) {}
                    FS.writeFile('/__shim_log', prev + msg + '\n');
                  } catch (e) {}
                }
                function memfsResolve(rel) {
                  var clean = String(rel).replace(/^:+/, '').replace(/^\/+/, '');
                  if (!clean) return null;
                  var base = clean.split('/').pop();
                  var cands = [
                    '/' + clean,
                    '/sim/lib/' + base,
                    '/sim/driver/js/' + base,
                    '/sim/' + clean,
                  ];
                  // framework shim 的 preload 目錄：/_wsp/{design}/{根,src,page}/
                  try {
                    var wspRoot = FS.analyzePath('/_wsp');
                    if (wspRoot.exists) {
                      var designDirs = FS.readdir('/_wsp');
                      for (var di = 0; di < designDirs.length; di++) {
                        var dn = designDirs[di];
                        if (dn === '.' || dn === '..') continue;
                        var subs = ['', '/src', '/page'];
                        for (var si = 0; si < subs.length; si++) {
                          var p = '/_wsp/' + dn + subs[si] + '/' + base;
                          try { if (FS.analyzePath(p).exists) return p; } catch (e) {}
                        }
                      }
                    }
                  } catch (e) {}
                  for (var ci = 0; ci < cands.length; ci++) {
                    try { if (FS.analyzePath(cands[ci]).exists) return cands[ci]; } catch (e) {}
                  }
                  return null;
                }
                // firmware 的 importer 對「點號 package 名」（ui.lvgl.registry）不拆解，
                // 直接找 ui.lvgl.registry.py 檔（404）。實務上板端 .py 都用平級檔名
                // （registry.py / control_panel.py），所以把點號名正規化成「最後一段」。
                // URL 版本也拆最後一段檔名的點號（.../ui/ui.lvgl.registry.py → .../ui/registry.py）。
                function normalizeModuleName(raw) {
                  var n = String(raw);
                  var isHttp = /^https?:\/\//i.test(n);
                  var prefix = '';
                  if (!isHttp && n.charAt(0) === ':') { prefix = ':'; n = n.slice(1); }
                  var slashIdx = n.lastIndexOf('/');
                  var dir = slashIdx >= 0 ? n.slice(0, slashIdx + 1) : '';
                  var fname = slashIdx >= 0 ? n.slice(slashIdx + 1) : n;
                  var stem = fname.endsWith('.py') ? fname.slice(0, -3) : fname;
                  var last = stem.split('.').pop();
                  if (last === stem) return raw;  // 無點號，不變
                  return prefix + dir + last + '.py';
                }
                var origExists = window.wasm_file_exists;
                var origOpen = window.wasm_file_open;
                // 裸模組名（無斜線、無 http）MEMFS 沒有 → 直接快速失敗。
                // 原 wasm_file_api 對相對路徑根本無法解析（無 ?script=），只會對
                // 一串候選 URL 逐個 404（uos/os/urequests 等非 builtin import 的
                // 請求風暴），快速失敗省掉整串探測。
                function bareLocalFail(norm) {
                  return norm.indexOf('/') < 0 && !/^https?:/i.test(norm);
                }
                window.wasm_file_exists = function (name, flag) {
                  var norm = normalizeModuleName(name);
                  try {
                    var hit = memfsResolve(norm);
                    shimLog('exists name=' + JSON.stringify(name) + ' norm=' + JSON.stringify(norm) + ' hit=' + hit);
                    if (hit) return 1;
                  } catch (e) {}
                  if (bareLocalFail(norm)) return -1;
                  return origExists ? origExists(norm, flag) : -1;
                };
                window.wasm_file_open = function (name, dest) {
                  var norm = normalizeModuleName(name);
                  var hit = null;
                  try { hit = memfsResolve(norm); } catch (e) {}
                  shimLog('open name=' + JSON.stringify(name) + ' norm=' + JSON.stringify(norm) + ' dest=' + JSON.stringify(dest) + ' hit=' + hit);
                  if (hit) {
                    try {
                      var data = FS.readFile(hit);
                      // 完全模仿原始 wasm_file_open 的回傳語意：
                      //   dest 有值 → 寫到 dest，回傳 length
                      //   dest 無值 → 寫到 /cache_{id}（id 遞增），回傳 id
                      // firmware 用回傳值當 handle 去讀 /cache_{id}。
                      var r = (typeof dest === 'string' && dest) ? dest : null;
                      window.urls.id += 1;
                      var a = data.length;
                      if (!r) { r = 'cache_' + window.urls.id; a = window.urls.id; }
                      try { FS.unlink('/' + r); } catch (e) {}
                      FS.createDataFile('/', r, data, true, true);
                      shimLog('  open SERVED len=' + data.length + ' dest=' + r + ' ret=' + a);
                      return a;
                    } catch (e) { shimLog('  open serve-err ' + e); }
                  }
                  if (bareLocalFail(norm)) return -1;
                  return origOpen ? origOpen(norm, dest) : -1;
                };
                try { FS.writeFile('/__shim_installed', 'ok'); } catch (e) {}
                shimLog('SHIM INSTALLED at ' + Date.now());
                console.log("[wasm_file_api] MEMFS-first shim installed");
              } else {
                console.log("[wasm_file_api] shim NOT installed: wasm_file_open=" + typeof window.wasm_file_open + " FS=" + typeof FS);
              }
            })();
            // --- END LVGL UI STUDIO ---

var compressedScript = (_simConfig && _simConfig.cscript) || null;
			if(compressedScript !== undefined && compressedScript !== null) {
                try {
                    await decompressScript(compressedScript);
                } catch(e) {
                    console.error(e);
                    sendText("An error occured while loading, check browser console");
                    window.top.reenableButton();
                    return;
                }
            }

			/*Setup lv_task_handler loop*/
            var the_mp_handle_pending = Module.cwrap('mp_handle_pending', null, [], { async: true });
            var lastPromise = null;
			async function handle_pending() {
                var startTime = performance.now();
                while(inputChars.length > 0) {
                    c = inputChars.shift();
                    if(c == 3 && currentSleepingResolve != null) {
                        currentSleepingResolve();
                        if(lastPromise != null) {
                            await lastPromise;
                            lastPromise = null;
                        }
                    } else {
                        if(lastPromise != null) {
                            await lastPromise;
                            lastPromise = null;
                        }
                        lastPromise = mp_js_process_char(c);
                    }
                }

                if(currentSleepingResolve == null) {
                    if(lastPromise != null) {
                        await lastPromise;
                    }
                    lastPromise = the_mp_handle_pending();
                }
                setTimeout(handle_pending, Math.max(0, 5-(performance.now()-startTime)));
			}
			/*Initialize the REPL.*/
                        mp_js_init_repl();
			/*Start the main loop, asynchronously.*/
			handle_pending();
			_simAck();
			try { window.top.reenableButton(); } catch (e) {}
		}
                window.process_char = function(c) {
                    inputChars.push(c);
                }
    