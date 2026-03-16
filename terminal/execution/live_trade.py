#!/usr/bin/env python3
"""
NemoFish Live CLOB Trader — Atomic E2E Script
Places real bets on Polymarket via CLOB API.
"""
import sys, os, json, time, hashlib, hmac, base64, traceback, requests
from eth_account import Account
from eth_utils import keccak
from eth_abi import encode

# Load env
env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
with open(env_path) as f:
    for l in f:
        l = l.strip()
        if l and not l.startswith('#') and '=' in l:
            k, v = l.split('=', 1)
            os.environ[k.strip()] = v.strip()

pk = os.environ['POLYMARKET_PRIVATE_KEY']
acct = Account.from_key(pk)
funder = os.environ.get('POLYMARKET_WALLET', acct.address)
print(f"Signer: {acct.address}")
print(f"Funder: {funder}")

CHAIN_ID = 137
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
NEG_RISK_CTF = "0xC5d563A36AE78145C45a50134d48A1215220f80a"

def khash(data):
    if isinstance(data, str): data = data.encode()
    return keccak(data)

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Origin': 'https://polymarket.com',
    'Referer': 'https://polymarket.com/',
})

# ========= STEP 1: L2 AUTH =========
print("\n🔑 Deriving L2 API credentials...")
DT = khash('EIP712Domain(string name,string version,uint256 chainId)')
ds = khash(DT + khash('ClobAuthDomain') + khash('1') + encode(['uint256'], [CHAIN_ID]))
CT = khash('ClobAuth(address address,string timestamp,uint256 nonce,string message)')

ts = int(time.time())
nonce_auth = 0
msg = 'This message attests that I control the given wallet'
sh = khash(CT + encode(['address'], [acct.address]) + khash(str(ts)) + encode(['uint256'], [nonce_auth]) + khash(msg))
digest = khash(b'\x19\x01' + ds + sh)
sig = Account._sign_hash(digest, pk)
sig_hex = '0x' + sig.signature.hex()

l1_headers = {
    'POLY_ADDRESS': acct.address,
    'POLY_SIGNATURE': sig_hex,
    'POLY_TIMESTAMP': str(ts),
    'POLY_NONCE': str(nonce_auth),
    'Content-Type': 'application/json',
}

# Try create, fall back to derive
resp = session.post('https://clob.polymarket.com/auth/api-key', headers=l1_headers)
if resp.status_code != 200:
    resp = session.get('https://clob.polymarket.com/auth/derive-api-key', headers=l1_headers)

if resp.status_code != 200:
    print(f"❌ L2 auth failed ({resp.status_code}): {resp.text[:200]}")
    sys.exit(1)

creds = resp.json()
api_key = creds['apiKey']
secret_key = creds['secret']
passphrase = creds['passphrase']
print(f"  ✅ apiKey: {api_key[:15]}...")

def build_hmac_sig(sec, ts, method, path, body=None):
    msg = str(ts) + str(method) + str(path)
    if body:
        msg += str(body).replace("'", '"')
    h = hmac.new(base64.urlsafe_b64decode(sec), msg.encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(h.digest()).decode()

def l2h(method, path, body=None):
    ts = str(int(time.time()))
    return {
        'POLY_ADDRESS': acct.address,
        'POLY_SIGNATURE': build_hmac_sig(secret_key, ts, method, path, body),
        'POLY_TIMESTAMP': ts,
        'POLY_API_KEY': api_key,
        'POLY_PASSPHRASE': passphrase,
    }

# ========= STEP 2: CHECK MARKETS =========
tokens = {
    'Riedi (vs Hanfmann)': ('6106521054476337617941823469564436560295039846703599931442543538579972315947', '+12.7%'),
    'Bolt (vs Shimabukuro)': ('51734084248484700674303669921324650276139592581497137569907980120781608151387', '+18.1%'),
    'Hanfmann (vs Riedi)': ('107668229876907902606071796642496573918963445480119272657368710710293059321377', ''),
    'Llamas Ruiz': ('68618572282514696386198225243358033312701770800757954954241579918026783368165', ''),
    'PJ Jones': ('39382808707011975288066702880166378360222753155260648569790399557434408091650', ''),
    'C Wong': ('88141643061548365498077949613135850854516298028395604673130757527770032392945', ''),
}

print(f"\n{'='*60}")
print("📊 Checking order books...")
active = []
for name, (tid, edge) in tokens.items():
    try:
        r = session.get(f'https://clob.polymarket.com/book?token_id={tid}', timeout=5)
        book = r.json()
        bids = book.get('bids', [])
        asks = book.get('asks', [])
        bb = float(bids[0]['price']) if bids else 0.0
        ba = float(asks[0]['price']) if asks else 1.0
        bs = float(bids[0]['size']) if bids else 0.0
        az = float(asks[0]['size']) if asks else 0.0
        spread = ba - bb
        
        if spread < 0.5 and ba < 0.90 and bb > 0.05:
            print(f"  ✅ {name}: {bb:.2f}/{ba:.2f} (spread {spread:.2f}, ask_sz={az:.0f}) edge={edge}")
            active.append({'name': name, 'token_id': tid, 'best_ask': ba, 'ask_size': az, 'edge': edge})
        else:
            print(f"  ⏭  {name}: {bb:.2f}/{ba:.2f} (spread={spread:.2f})")
    except Exception as e:
        print(f"  ❌ {name}: {e}")
    time.sleep(0.3)

if not active:
    print("\n⚠️ No active markets with liquidity. Matches may have ended.")
    print("  Try refreshing tokens from https://polymarket.com/sports/atp/games")
    sys.exit(0)

# ========= STEP 3: PLACE ORDERS =========
print(f"\n{'='*60}")
print(f"🎯 Found {len(active)} tradeable markets")

for mkt in active[:2]:
    token_id = mkt['token_id']
    name = mkt['name']
    price = mkt['best_ask']
    amount_usd = 1.0

    # Shares calculation
    shares = round(amount_usd / price, 2)
    maker_amount = int(round(amount_usd, 2) * 1_000_000)
    taker_amount = int(round(shares, 2) * 1_000_000)

    print(f"\n📈 BUY {name} @ {price:.2f} | ${amount_usd} → {shares:.1f} shares")

    # Neg risk check
    nr = session.get(f'https://clob.polymarket.com/neg-risk?token_id={token_id}').json().get('neg_risk', False)
    exchange = NEG_RISK_CTF if nr else CTF_EXCHANGE

    # Fee rate
    fee = session.get(f'https://clob.polymarket.com/fee-rate?token_id={token_id}').json().get('base_fee', 0)
    fee = int(fee) if fee else 0

    # Sign EIP-712 order
    ORDER_TH = khash("Order(uint256 salt,address maker,address signer,address taker,uint256 tokenId,uint256 makerAmount,uint256 takerAmount,uint256 expiration,uint256 nonce,uint256 feeRateBps,uint8 side,uint8 signatureType)")
    DOMAIN_TH = khash("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
    dom = khash(DOMAIN_TH + khash("Polymarket CTF Exchange") + khash("1") + encode(['uint256'], [CHAIN_ID]) + encode(['address'], [exchange]))

    salt = int(time.time() * 1000)
    sh = khash(
        ORDER_TH +
        encode(['uint256'], [salt]) +
        encode(['address'], [acct.address]) +
        encode(['address'], [acct.address]) +
        encode(['address'], ['0x0000000000000000000000000000000000000000']) +
        encode(['uint256'], [int(token_id)]) +
        encode(['uint256'], [maker_amount]) +
        encode(['uint256'], [taker_amount]) +
        encode(['uint256'], [0]) +
        encode(['uint256'], [0]) +
        encode(['uint256'], [fee]) +
        encode(['uint8'], [0]) +
        encode(['uint8'], [2])
    )
    d = khash(b'\x19\x01' + dom + sh)
    s = Account._sign_hash(d, pk)
    s_hex = '0x' + s.signature.hex()

    body = {
        "order": {
            "salt": str(salt),
            "maker": acct.address,
            "signer": acct.address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": token_id,
            "makerAmount": str(maker_amount),
            "takerAmount": str(taker_amount),
            "expiration": "0",
            "nonce": "0",
            "feeRateBps": str(fee),
            "side": "BUY",
            "signatureType": 2,
            "signature": s_hex,
        },
        "owner": acct.address,
        "orderType": "GTC",
    }

    ser = json.dumps(body, separators=(',', ':'), ensure_ascii=False)
    hdrs = l2h('POST', '/order', ser)
    hdrs['Content-Type'] = 'application/json'

    resp = session.post('https://clob.polymarket.com/order', headers=hdrs, data=ser)
    print(f"  Response ({resp.status_code}): {resp.text[:400]}")

    if resp.status_code == 200:
        r = resp.json()
        oid = r.get('orderID', r.get('id', ''))
        print(f"  ✅ ORDER ID: {oid}")
    time.sleep(1)

print(f"\n{'='*60}")
print("🐡 NemoFish CLOB Trading Session Complete")
