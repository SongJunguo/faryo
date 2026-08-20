const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export function sessionApiPath(path, session = "") {
  if (!session || !String(path).startsWith("/api/")) return String(path);
  const separator = String(path).includes("?") ? "&" : "?";
  return `${path}${separator}session=${encodeURIComponent(session)}`;
}

export function createApiClient(options = {}) {
  const routeBase = String(options.routeBase || "");
  const ownerToken = String(options.ownerToken || "");
  const fetchRequest = options.fetch;
  const FormDataType = options.FormData || globalThis.FormData;
  if (typeof fetchRequest !== "function") throw new TypeError("Owner API client requires fetch");
  let gatewayCsrfToken = "";

  function ownerHeaders() {
    return ownerToken ? { "X-Owner-Token": ownerToken } : {};
  }

  async function csrfHeaders() {
    if (!routeBase || ownerToken) return {};
    if (!gatewayCsrfToken) {
      const response = await fetchRequest("/api/csrf", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.csrf) {
        const error = new Error(data.error || "CSRF token unavailable");
        error.status = response.status;
        throw error;
      }
      gatewayCsrfToken = data.csrf;
    }
    return { "X-Faryo-Csrf": gatewayCsrfToken };
  }

  async function request(path, requestOptions = {}) {
    const headers = { ...(requestOptions.headers || {}), ...ownerHeaders() };
    const method = String(requestOptions.method || "GET").toUpperCase();
    if (!SAFE_METHODS.has(method)) Object.assign(headers, await csrfHeaders());
    const isFormData = Boolean(
      requestOptions.body
      && typeof FormDataType === "function"
      && requestOptions.body instanceof FormDataType
    );
    if (requestOptions.body && !headers["Content-Type"] && !isFormData) {
      headers["Content-Type"] = "application/json";
    }
    const requestPath = String(path).startsWith("/api/") ? `${routeBase}${path}` : String(path);
    const response = await fetchRequest(requestPath, {
      ...requestOptions,
      headers,
      cache: "no-store",
    });
    const text = await response.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch (_error) {
      const error = new Error(
        response.ok
          ? "API response is not JSON"
          : `${response.status} ${response.statusText || "API error"}`,
      );
      error.status = response.status;
      error.nonJson = true;
      throw error;
    }
    if (!response.ok || data.ok === false) {
      const error = new Error(data.error || `${response.status} ${response.statusText}`);
      error.status = response.status;
      error.payload = data;
      throw error;
    }
    return data;
  }

  return {
    request,
    csrfHeaders,
    ownerHeaders,
    hasOwnerToken: Boolean(ownerToken),
  };
}
