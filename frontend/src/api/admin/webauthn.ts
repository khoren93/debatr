/**
 * Passkeys in the browser: the server's WebAuthn options (JSON, base64url fields) go to
 * navigator.credentials, and the credential comes back as JSON for the server to verify
 * (backend/app/services/admin/passkeys.py). Converted by hand rather than with
 * `PublicKeyCredential.parse*FromJSON` / `toJSON`, which not every browser (or password-manager
 * extension) provides yet.
 */

type Json = Record<string, unknown>;

const fromBase64url = (value: string): ArrayBuffer => {
  const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
  const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
};

const toBase64url = (buffer: ArrayBuffer): string => {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};

const descriptors = (list: unknown): PublicKeyCredentialDescriptor[] | undefined =>
  Array.isArray(list) ? list.map((item: Json) => ({ ...item, id: fromBase64url(String(item.id)) }) as PublicKeyCredentialDescriptor) : undefined;

/** Whether this browser can use passkeys at all. */
export const passkeysSupported = (): boolean => typeof window !== 'undefined' && 'PublicKeyCredential' in window && Boolean(navigator.credentials);

const friendly = (err: unknown, creating: boolean): Error => {
  const name = err instanceof DOMException ? err.name : '';
  if (name === 'NotAllowedError' || name === 'AbortError') return new Error('The passkey prompt was closed or timed out', { cause: err });
  if (name === 'InvalidStateError' && creating) return new Error('This passkey is already registered', { cause: err });
  if (name === 'SecurityError') return new Error('Passkeys need the console’s own https address', { cause: err });
  return err instanceof Error ? err : new Error('The passkey did not answer', { cause: err });
};

/** Creates a passkey with the server's registration options; resolves to its JSON. */
export const createPasskey = async (options: Json): Promise<Json> => {
  const user = options.user as Json;
  const publicKey = {
    ...options,
    challenge: fromBase64url(String(options.challenge)),
    user: { ...user, id: fromBase64url(String(user.id)) },
    excludeCredentials: descriptors(options.excludeCredentials),
  } as unknown as PublicKeyCredentialCreationOptions;
  let credential: Credential | null;
  try {
    credential = await navigator.credentials.create({ publicKey });
  } catch (err) {
    throw friendly(err, true);
  }
  if (!(credential instanceof PublicKeyCredential)) throw new Error('The passkey did not answer');
  const response = credential.response as AuthenticatorAttestationResponse;
  return {
    id: credential.id,
    rawId: toBase64url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: {
      clientDataJSON: toBase64url(response.clientDataJSON),
      attestationObject: toBase64url(response.attestationObject),
      transports: typeof response.getTransports === 'function' ? response.getTransports() : [],
    },
  };
};

/** Asks for one of the account's passkeys with the server's options; resolves to the answer. */
export const getPasskey = async (options: Json): Promise<Json> => {
  const publicKey = {
    ...options,
    challenge: fromBase64url(String(options.challenge)),
    allowCredentials: descriptors(options.allowCredentials),
  } as unknown as PublicKeyCredentialRequestOptions;
  let credential: Credential | null;
  try {
    credential = await navigator.credentials.get({ publicKey });
  } catch (err) {
    throw friendly(err, false);
  }
  if (!(credential instanceof PublicKeyCredential)) throw new Error('The passkey did not answer');
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    id: credential.id,
    rawId: toBase64url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: {
      clientDataJSON: toBase64url(response.clientDataJSON),
      authenticatorData: toBase64url(response.authenticatorData),
      signature: toBase64url(response.signature),
      userHandle: response.userHandle ? toBase64url(response.userHandle) : null,
    },
  };
};
