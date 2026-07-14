"""Quick test to verify broker imports and SSID parsing."""
from infrastructure.broker.pocket_option import PocketOptionBroker, _parse_ssid
from config.settings import BrokerConfig

# Test SSID parsing
ssid_raw = '42["auth",{"session":"AY7fG7xNFAC6M2_Rp","isDemo":1,"uid":90292458,"platform":1}]'
session, meta = _parse_ssid(ssid_raw)
print(f"Session: {session}")
print(f"Meta: {meta}")

# Test broker instantiation
config = BrokerConfig(ssid=ssid_raw, region="eu")
broker = PocketOptionBroker(config)
print(f"Broker created, client type: {type(broker._client).__name__}")
print(f"Connected: {broker._connected}")
print("OK - broker imports and parses correctly")
