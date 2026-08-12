// SimLab runtime boot test: load built micropython.mjs, boot, check lvgl API surface
import { loadMicroPython } from "./micropython.js";

const mp = await loadMicroPython({
    heapsize: 4 * 1024 * 1024,
    stdout: (s) => console.log("[py]", s),
    stderr: (s) => console.error("[py-err]", s),
});
console.log("=== booted ===");

// version
const sys = mp.pyimport("sys");
console.log("implementation:", mp.runPython("import sys; str(sys.implementation)"));
console.log("platform:", mp.runPython("import sys; sys.platform"));

// lvgl module surface
const lv = mp.pyimport("lvgl");
console.log("lvgl module ok:", !!lv);
const checks = ["display_create", "sdl_window_create", "sdl_mouse_create", "task_handler", "tick_inc", "init", "is_initialized", "refr_now", "draw_sw_rgb565_swap"];
for (const name of checks) {
    console.log("lv." + name + ":", typeof lv[name]);
}

// run some python
mp.runPython("import lvgl as lv; print('LVGL', lv.version_info)");

// sleep 測試(asyncify rewind)
console.log("=== sleep test ===");
const t0 = Date.now();
const r = await mp.runPythonAsync("import time; time.sleep_ms(5); print('slept ok')");
console.log("sleep result:", r, "elapsed:", Date.now() - t0, "ms");

// 迴圈測試
console.log("=== loop test ===");
const r2 = await mp.runPythonAsync("s = 0\nfor i in range(1000): s += i\nprint('sum', s)");
console.log("loop result:", r2);

// JS 模組橋測試(registerJsModule + bytes 傳遞)
console.log("=== js bridge test ===");
mp.registerJsModule("simlab_canvas", {
    putPixels: (x, y, w, h, data) => {
        let arr = data;
        try { arr = mp.PyProxy.toJs(data); } catch (e) { console.log("toJs err:", e); }
        console.log("JS putPixels:", x, y, w, h, "len:", arr && arr.length, "isU8:", arr instanceof Uint8Array);
        return 1;
    },
});
const r3 = await mp.runPythonAsync(`
import simlab_canvas
r = simlab_canvas.putPixels(1, 2, 3, 4, bytes([1,2,3,4,5,6]))
print('python got return:', r)
print('js bridge ok')
`);
console.log("bridge result:", r3);

console.log("=== done ===");
process.exit(0);
