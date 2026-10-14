export function getAccessTokenExpiration(token: string | null): number | null {
  if (!token) {
    return null
  }

  const [header, payload, signature, ...extraParts] = token.split('.')
  if (!header || !payload || !signature || extraParts.length > 0) {
    return null
  }

  try {
    const normalizedPayload = payload
      .replace(/-/g, '+')
      .replace(/_/g, '/')
      .padEnd(Math.ceil(payload.length / 4) * 4, '=')
    const claims: unknown = JSON.parse(atob(normalizedPayload))

    if (
      typeof claims !== 'object' ||
      claims === null ||
      !('exp' in claims) ||
      typeof claims.exp !== 'number' ||
      !Number.isFinite(claims.exp)
    ) {
      return null
    }

    return claims.exp
  } catch {
    return null
  }
}

export function hasUnexpiredAccessToken(
  token: string | null,
  now = Date.now(),
): boolean {
  const expiration = getAccessTokenExpiration(token)
  return expiration !== null && expiration * 1000 > now
}
