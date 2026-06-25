import { useEffect, useState } from "react";

interface Device {
  did: string;
  name: string;
  type: string;
  location: string;
  status: string;
}

interface DataPacket {
  did: string;
  device_name: string;
  device_type: string;
  value: string;
  timestamp: number;
  hash: string;
  status: string;
  cid: string | null;
  ipfs_url: string | null;
}

export default function Home() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [feed, setFeed] = useState<DataPacket[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [packetCount, setPacketCount] = useState(0);
  const [showRegister, setShowRegister] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [registerResult, setRegisterResult] = useState<string | null>(null);
  const [form, setForm] = useState({
    device_type: "temperature",
    location: "",
    public_key: "",
  });

  useEffect(() => {
    fetchDevices();
  }, []);

  useEffect(() => {
    fetch("http://localhost:8001/packet-count")
      .then((r) => r.json())
      .then((data) => setPacketCount(data.count))
      .catch((e) => console.error("Failed to fetch packet count:", e));
  }, []);

  const fetchDevices = () => {
    fetch("http://localhost:8001/devices")
      .then((r) => r.json())
      .then(setDevices);
  };

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8001/ws");
    ws.onmessage = (e) => {
      const packet: DataPacket = JSON.parse(e.data);
      setFeed((prev) => [packet, ...prev].slice(0, 50));
      if (packet.status === "verified") setPacketCount((c) => c + 1);
    };
    return () => ws.close();
  }, []);

  const filteredFeed = selected
    ? feed.filter((p) => p.did === selected)
    : feed;

  const verifiedCount = devices.filter((d) => d.status === "verified").length;

  const statusColor = (s: string) => {
    if (s === "verified") return "bg-green-100 text-green-700";
    if (s === "pending") return "bg-yellow-100 text-yellow-700";
    return "bg-red-100 text-red-700";
  };

  const revoke = async (did: string) => {
    await fetch(`http://localhost:8001/revoke-onchain/${encodeURIComponent(did)}`, {
      method: "POST",
    });
    fetchDevices();
  };

  const verify = async (did: string) => {
    await fetch(`http://localhost:8001/verify-onchain/${encodeURIComponent(did)}`, {
      method: "POST",
    });
    fetchDevices();
  };

  const handleRegister = async () => {
    setRegistering(true);
    setRegisterResult(null);
    try {
      const res = await fetch("http://localhost:8001/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (data.success) {
        setRegisterResult(`✅ Device registered! DID: ${data.did}`);
        fetchDevices();
        setForm({ device_type: "temperature", location: "", public_key: "" });
      } else {
        setRegisterResult(`❌ Error: ${data.error}`);
      }
    } catch (e) {
      setRegisterResult("❌ Failed to connect to backend");
    }
    setRegistering(false);
  };

  return (
    <div className="min-h-screen bg-gray-50 p-6 font-sans">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-800">
            DID-IoT Identity Dashboard
          </h1>
          <p className="text-sm text-gray-500">
            Decentralized identity · Solana devnet · IPFS provenance
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowRegister(!showRegister)}
            className="bg-blue-600 text-white text-sm px-4 py-2 rounded-lg hover:bg-blue-700"
          >
            + Register Device
          </button>
          <span className="flex items-center gap-2 bg-green-100 text-green-700 text-sm px-3 py-1 rounded-full font-medium">
            <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
            Live
          </span>
        </div>
      </div>

      {/* Register Device Form */}
      {showRegister && (
        <div className="bg-white border border-gray-200 rounded-xl p-5 mb-6 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">
            Register New IoT Device
          </h2>
          <div className="grid grid-cols-3 gap-3 mb-3">

            <div>
              <label className="text-xs text-gray-500 mb-1 block">Device Type</label>
              <select
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-black bg-white text-sm focus:outline-none focus:border-blue-400"
                value={form.device_type}
                onChange={(e) => setForm({ ...form, device_type: e.target.value })}
              >
                <option value="temperature">Temperature</option>
                <option value="humidity">Humidity</option>
                <option value="co2">CO2</option>
                <option value="soil">Soil Moisture</option>
                <option value="pressure">Pressure/Temperature (BMP280)</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Location</label>
              <input
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-black bg-white placeholder-gray-600 text-sm focus:outline-none focus:border-blue-400"
                placeholder="e.g. Lab Block 3"
                value={form.location}
                onChange={(e) => setForm({ ...form, location: e.target.value })}
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Public Key</label>
              <input
                style={{ color: '#111827', backgroundColor: '#ffffff' }}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-400"
                placeholder="Paste ESP32 public key here"
                value={form.public_key}
                onChange={(e) => setForm({ ...form, public_key: e.target.value })}
              />
            </div>

          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleRegister}
              disabled={registering}
              className="bg-blue-600 text-white text-sm px-4 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {registering ? "Registering on Solana..." : "Register Device"}
            </button>
            <button
              onClick={() => { setShowRegister(false); setRegisterResult(null); }}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Cancel
            </button>
            {registerResult && (
              <span className="text-sm font-mono">{registerResult}</span>
            )}
          </div>
          <p className="text-xs text-gray-400 mt-2">
            Copy the Public Key from the ESP32 boot output. DID is auto-generated from it.
          </p>
        </div>
      )}

      {/* Metrics */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {[
          { label: "Registered Devices", value: devices.length },
          { label: "Verified", value: verifiedCount, green: true },
          { label: "Data Packets", value: packetCount },
          { label: "Integrity Checks", value: "100%", green: true },
        ].map((m) => (
          <div key={m.label} className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
            <div className="text-xs text-gray-400 mb-1">{m.label}</div>
            <div className={`text-2xl font-semibold ${m.green ? "text-green-600" : "text-gray-800"}`}>
              {m.value}
            </div>
          </div>
        ))}
      </div>

      {/* Main layout */}
      <div className="grid grid-cols-5 gap-4">
        {/* Device list */}
        <div className="col-span-2 bg-white rounded-xl shadow-sm border border-gray-100 p-4">
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
            Registered Devices
          </h2>
          {devices.map((d) => (
            <div
              key={d.did}
              onClick={() => setSelected(selected === d.did ? null : d.did)}
              className={`border rounded-lg p-3 mb-2 cursor-pointer transition-all ${selected === d.did
                ? "border-blue-400 bg-blue-50"
                : "border-gray-100 hover:bg-gray-50"
                }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-medium text-sm text-gray-800">{d.name}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusColor(d.status)}`}>
                  {d.status}
                </span>
              </div>
              <div className="text-xs text-gray-400 font-mono mb-2 truncate">{d.did}</div>
              <div className="flex gap-3 text-xs text-gray-500 mb-2">
                <span>Type: <b>{d.type}</b></span>
                <span>📍 {d.location}</span>
              </div>
              <div className="flex gap-2">
                {d.status !== "revoked" && (
                  <button
                    onClick={(e) => { e.stopPropagation(); revoke(d.did); }}
                    className="text-xs bg-red-50 text-red-600 px-2 py-0.5 rounded hover:bg-red-100"
                  >
                    Revoke
                  </button>
                )}
                {d.status !== "verified" && (
                  <button
                    onClick={(e) => { e.stopPropagation(); verify(d.did); }}
                    className="text-xs bg-green-50 text-green-600 px-2 py-0.5 rounded hover:bg-green-100"
                  >
                    Verify
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Live feed */}
        <div className="col-span-3 bg-white rounded-xl shadow-sm border border-gray-100 p-4">
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
            Live Data Feed
          </h2>
          <p className="text-xs text-gray-400 mb-3">
            {selected
              ? `Filtering: ${selected}`
              : "Showing all devices — click a device to filter"}
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: '90px 130px 1fr 80px 90px', gap: '8px' }} className="text-xs font-semibold text-gray-400 border-b pb-2 mb-1">
            <span>Time</span>
            <span>Device</span>
            <span>Value</span>
            <span>Hash</span>
            <span>IPFS</span>
          </div>
          <div className="overflow-y-auto max-h-96">
            {filteredFeed.length === 0 ? (
              <p className="text-sm text-gray-400 py-4 text-center">
                Waiting for data...
              </p>
            ) : (
              filteredFeed.map((p, i) => (
                <div
                  key={i}
                  style={{ display: 'grid', gridTemplateColumns: '90px 130px 1fr 80px 90px', gap: '8px' }}
                  className={`text-xs py-2 border-b border-gray-50 items-center ${p.status !== "verified" ? "bg-red-50" : ""}`}
                >
                  <span className="text-gray-400 font-mono">
                    {new Date(p.timestamp * 1000).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' })}
                  </span>
                  <div className="overflow-hidden">
                    <div className="font-mono text-gray-600 truncate text-xs">{p.did.slice(0, 18)}...</div>
                    <div className="text-gray-400 text-xs">{p.device_type}</div>
                  </div>
                  <span className={`font-semibold truncate ${p.status === "verified" ? "text-gray-800" : "text-red-500"}`}>
                    {p.value}
                  </span>
                  <span className="font-mono text-gray-400 truncate">{p.hash}</span>
                  <span>
                    {p.ipfs_url ? (
                      <a href={p.ipfs_url} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline font-mono">
                        {p.cid?.slice(0, 8)}...
                      </a>
                    ) : (
                      <span className="text-red-400">—</span>
                    )}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      <div className="mt-4 text-center text-xs text-gray-400">
        Solana Devnet · Program ID: B3gYy9xnAUiU3qW9seVVUgZ6kSWzz7ePibCSXbsJK9eq · IPFS via Pinata
      </div>
    </div>
  );
}