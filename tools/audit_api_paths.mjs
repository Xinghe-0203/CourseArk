// 前端请求路径 ↔ 后端路由的一致性审计（只读）。
//
// 用法：node tools/audit_api_paths.mjs
//
// 目的：靠人眼比对「前端调了 /api/xxx 而后端没注册」很容易漏，漏了浏览器只会
// 看到 404，而 ApiError 还会把响应体缺失兜成通用文案。这里用文本扫描把两边的
// 路径集合抽出来做形状匹配（参数段统一折叠成 :x），不依赖运行时。
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

const SKIP_DIRS = new Set(["node_modules", "dist", ".git", "__pycache__"]);

function walkFiles(dir, extensions, out = []) {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) {
      if (SKIP_DIRS.has(name)) continue;
      walkFiles(full, extensions, out);
    } else if (extensions.some((ext) => name.endsWith(ext))) {
      out.push(full);
    }
  }
  return out;
}

// ---------- 后端：@router.get("/api/...") / @app.post('/api/...') ----------
const ROUTE_RE = /@(?:router|app|main\.app)\.(?:get|post|patch|put|delete)\(\s*["']([^"']+)["']/g;
const routes = new Set();
for (const file of walkFiles("app", [".py"])) {
  const text = readFileSync(file, "utf8");
  for (const match of text.matchAll(ROUTE_RE)) routes.add(match[1]);
}

// ---------- 前端：request(...) / fetch(...) 的第一个参数 ----------
// request<T>(path) 的泛型里可能含 <> 或 {}，所以用 [^(]* 跳过泛型再取引号字面量。
const CALL_RE = /(?:request|fetch)\b[^(]*\(\s*([`"'][^`"']*[`"'])/g;
const requested = new Map(); // 绝对路径 → 首次出现的文件
for (const file of walkFiles("frontend/src", [".ts", ".vue"])) {
  if (file.endsWith(".test.ts")) continue;
  const text = readFileSync(file, "utf8");
  for (const match of text.matchAll(CALL_RE)) {
    const literal = match[1];
    let raw = literal.slice(1, -1);
    if (raw.startsWith("http")) continue;
    // request() 的路径相对 /api；api.ts 自身的 fetch("/api"+path) 已带前缀
    if (!raw.startsWith("/api")) {
      raw = "/api" + (raw.startsWith("/") ? "" : "/") + raw;
    }
    raw = raw.replace(/\$\{[^}]*\}/g, ":x");
    if (!requested.has(raw)) requested.set(raw, file);
  }
}

// 把查询串去掉、参数段折叠成 :x，便于形状比对。
const shape = (value) =>
  value
    .split("?")[0]
    .replace(/\{[^}]*\}/g, ":x")
    .replace(/\/+$/, "")
    .split("/")
    .filter(Boolean)
    .join("/");

function matches(absPath) {
  const target = shape(absPath);
  const right = target.split("/");
  for (const route of routes) {
    const left = shape(route).split("/");
    if (left.length !== right.length) continue;
    let ok = true;
    for (let i = 0; i < left.length; i += 1) {
      // FastAPI 用 {param}、前端用 ${...} 插值，两边都折叠成 :x —— 参数段互相放行
      if (left[i] === ":x" || right[i] === ":x") continue;
      if (left[i] !== right[i]) {
        ok = false;
        break;
      }
    }
    if (ok) return true;
  }
  return false;
}

// api.ts 自己把 "/api" 拼在 path 前面，那条字面量不是端点，跳过。
const missing = [...requested.keys()].filter((p) => !matches(p) && p !== "/api");
const unused = [...routes].filter(
  (route) =>
    route.startsWith("/api") &&
    ![...requested.keys()].some((p) => shape(p) === shape(route)),
);

console.log(`后端 /api 路由 ${routes.size} 条；前端请求字面量 ${requested.size} 条`);
if (missing.length) {
  console.log("\n[前端请求但后端没有对应路由]");
  for (const item of missing) console.log(`  ${item}    (${requested.get(item)})`);
} else {
  console.log("\n前端请求全部能匹配到后端路由。");
}
if (unused.length) {
  console.log("\n[后端有、前端未直接请求（可能由 SSE / 下载链接 / 工具脚本使用）]");
  for (const item of unused) console.log(`  ${item}`);
}
process.exit(missing.length ? 1 : 0);
