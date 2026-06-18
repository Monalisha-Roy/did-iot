# Minimal Ed25519 for MicroPython
import hashlib

def _clamp(k):
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    return k

P = 2**255 - 19
Q = 2**252 + 27742317777372353535851937790883648493

def _modp_inv(x):
    return pow(x, P-2, P)

d = -121665 * _modp_inv(121666) % P
sqrt_m1 = pow(2, (P-1)//4, P)

def _recover_x(y, sign):
    x2 = (y*y-1) * _modp_inv(d*y*y+1)
    if x2 == 0:
        return 0 if sign == 0 else None
    x = pow(x2, (P+3)//8, P)
    if (x*x - x2) % P != 0:
        x = x * sqrt_m1 % P
    if (x*x - x2) % P != 0:
        return None
    if x & 1 != sign:
        x = P - x
    return x

G = None

def _get_G():
    global G
    if G is None:
        gy = 4 * _modp_inv(5) % P
        gx = _recover_x(gy, 0)
        G = (gx, gy, 1, gx*gy % P)
    return G

def _point_add(P1, P2):
    A = P1[1]-P1[0], P1[1]+P1[0]
    B = P2[1]-P2[0], P2[1]+P2[0]
    a = A[0]*B[0] % P
    b = A[1]*B[1] % P
    c = P1[3]*P2[3]*2*d % P
    dd = P1[2]*P2[2]*2 % P
    e, f, g, h = b-a, dd-c, dd+c, b+a
    return e*f % P, g*h % P, f*g % P, e*h % P

def _point_mul(s, P1):
    Q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            Q = _point_add(Q, P1)
        P1 = _point_add(P1, P1)
        s >>= 1
    return Q

def _point_compress(P1):
    zinv = _modp_inv(P1[2])
    x = P1[0] * zinv % P
    y = P1[1] * zinv % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")

def _point_decompress(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= ~(1 << 255)
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x*y % P)

def _sha512(data):
    from sha512 import sha512
    return sha512(data) 

def keypair_from_seed(seed):
    h = _sha512(seed)
    a = bytearray(h[:32])
    _clamp(a)
    a = int.from_bytes(a, "little")
    A = _point_compress(_point_mul(a, _get_G()))
    return bytes(seed) + A, A

def sign(private_key, message):
    seed = private_key[:32]
    public_key = private_key[32:]
    h = _sha512(seed)
    a = bytearray(h[:32])
    _clamp(a)
    a = int.from_bytes(a, "little")
    r_hash = _sha512(h[32:] + message)
    r = int.from_bytes(r_hash, "little") % Q
    R = _point_compress(_point_mul(r, _get_G()))
    k_hash = _sha512(R + public_key + message)
    k = int.from_bytes(k_hash, "little") % Q
    S = (r + k * a) % Q
    return R + int.to_bytes(S, 32, "little")

def verify(public_key, message, signature):
    if len(public_key) != 32 or len(signature) != 64:
        return False
    A = _point_decompress(public_key)
    if A is None:
        return False
    R = _point_decompress(signature[:32])
    if R is None:
        return False
    S = int.from_bytes(signature[32:], "little")
    if S >= Q:
        return False
    k_hash = _sha512(signature[:32] + public_key + message)
    k = int.from_bytes(k_hash, "little") % Q
    gs = _point_mul(S, _get_G())
    kA = _point_mul(k, A)
    RkA = _point_add(R, kA)
    return _point_compress(gs) == _point_compress(RkA)
