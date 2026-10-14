function isInternalNavigation(candidateUrl, backendOrigin) {
  try {
    return new URL(candidateUrl).origin === new URL(backendOrigin).origin;
  } catch {
    return false;
  }
}

function externalHttpUrl(candidateUrl) {
  try {
    const target = new URL(candidateUrl);
    if (!new Set(["http:", "https:"]).has(target.protocol)) return null;
    if (target.username || target.password) return null;
    return target.href;
  } catch {
    return null;
  }
}

module.exports = { isInternalNavigation, externalHttpUrl };
