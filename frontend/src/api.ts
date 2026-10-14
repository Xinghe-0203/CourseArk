const inflight = new Map<string, Promise<unknown>>();
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const execute = async (): Promise<T> => {
    const controller = new AbortController();
    const timer = setTimeout(
      () => controller.abort(),
      path.includes("open-chaoxing") ? 65000 : 30000,
    );
    try {
      const response = await fetch("/api" + path, {
        method,
        signal: controller.signal,
        headers:
          body === undefined ? {} : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const value = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = value.detail;
        throw new ApiError(
          typeof detail === "string"
            ? detail
            : Array.isArray(detail)
              ? detail
                  .map(
                    (x: { loc: string[]; msg: string }) =>
                      `${x.loc.slice(1).join(" / ")}：${x.msg}`,
                  )
                  .join("；")
              : "服务暂时不可用，请稍后重试",
          response.status,
        );
      }
      return value as T;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new Error(
        error instanceof Error && error.name === "AbortError"
          ? "等待服务响应超时，请检查问题中心"
          : "无法连接本机服务，请检查启动窗口",
      );
    } finally {
      clearTimeout(timer);
    }
  };
  if (method !== "GET") return execute();
  if (inflight.has(path)) return inflight.get(path) as Promise<T>;
  const result = execute().finally(() => inflight.delete(path));
  inflight.set(path, result);
  return result;
}
