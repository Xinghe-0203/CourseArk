// Node 26 自带实验性 localStorage，未传 --localstorage-file 时是 undefined；
// jsdom 环境在部分 Vitest/Node 组合下也不会把 Storage 挂到 globalThis。
// 单测只关心「记住窗口几何/最小化」的行为，这里提供内存态 polyfill，
// 不改变应用运行时的 localStorage 逻辑。
class MemoryStorage implements Storage {
  private data = new Map<string, string>();

  get length() {
    return this.data.size;
  }

  clear() {
    this.data.clear();
  }

  getItem(key: string) {
    return this.data.has(key) ? this.data.get(key)! : null;
  }

  key(index: number) {
    return Array.from(this.data.keys())[index] ?? null;
  }

  removeItem(key: string) {
    this.data.delete(key);
  }

  setItem(key: string, value: string) {
    this.data.set(key, String(value));
  }
}

function install(name: "localStorage" | "sessionStorage") {
  let current: unknown;
  try {
    current = (globalThis as Record<string, unknown>)[name];
  } catch {
    current = undefined;
  }
  if (
    current &&
    typeof (current as Storage).getItem === "function" &&
    typeof (current as Storage).setItem === "function"
  ) {
    return;
  }
  const storage = new MemoryStorage();
  Object.defineProperty(globalThis, name, {
    value: storage,
    configurable: true,
    writable: true,
  });
  if (typeof window !== "undefined" && window !== (globalThis as unknown)) {
    try {
      Object.defineProperty(window, name, {
        value: storage,
        configurable: true,
        writable: true,
      });
    } catch {
      /* 某些环境 window 不可重定义，globalThis 已够用 */
    }
  }
}

install("localStorage");
install("sessionStorage");
