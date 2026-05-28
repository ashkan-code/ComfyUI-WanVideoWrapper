import { WalletState, WalletActions } from '../hooks/useWallet'

interface Props { wallet: WalletState & WalletActions }

export function WalletConnect({ wallet }: Props) {
  return (
    <div className="min-h-screen flex items-center justify-center p-6 relative overflow-hidden" style={{ background: '#07090f' }}>
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[700px] h-[700px] rounded-full"
             style={{ background: 'radial-gradient(circle, rgba(124,58,237,0.12) 0%, transparent 65%)' }} />
        <div className="absolute bottom-1/4 left-1/4 w-96 h-96 rounded-full"
             style={{ background: 'radial-gradient(circle, rgba(37,99,235,0.08) 0%, transparent 65%)' }} />
        <div className="absolute inset-0"
             style={{ backgroundImage: 'linear-gradient(rgba(139,92,246,0.04) 1px, transparent 1px), linear-gradient(to right, rgba(139,92,246,0.04) 1px, transparent 1px)', backgroundSize: '60px 60px' }} />
      </div>

      <div className="relative w-full max-w-sm">
        <div className="flex justify-center mb-8">
          <div className="w-20 h-20 rounded-3xl flex items-center justify-center float"
               style={{ background: 'linear-gradient(135deg, #7c3aed, #2563eb)', boxShadow: '0 20px 60px rgba(124,58,237,0.45), 0 0 0 1px rgba(255,255,255,0.08)' }}>
            <span className="text-4xl text-white">⟠</span>
          </div>
        </div>

        <h1 className="text-center text-3xl font-bold text-white mb-1">Web3 Unified Wallet</h1>
        <p className="text-center text-sm mb-8" style={{ color: '#334155' }}>Connect your wallet to continue</p>

        <div className="rounded-3xl p-1" style={{ background: 'linear-gradient(135deg, rgba(139,92,246,0.2), rgba(37,99,235,0.1), rgba(0,0,0,0))', padding: '1px' }}>
          <div className="rounded-3xl p-6" style={{ background: '#0d1117' }}>

            {wallet.error && (
              <div className="rounded-2xl p-3 mb-5 flex gap-2 text-sm"
                   style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.15)', color: '#fca5a5' }}>
                <span>⚠</span><span>{wallet.error}</span>
              </div>
            )}

            <div className="space-y-2">
              <button onClick={wallet.connect} disabled={wallet.isConnecting}
                className="w-full flex items-center gap-4 py-4 px-5 rounded-2xl transition-all duration-200 group disabled:opacity-60"
                style={{ background: 'linear-gradient(135deg, rgba(251,146,60,0.1), rgba(251,146,60,0.05))', border: '1px solid rgba(251,146,60,0.2)' }}>
                <span className="text-2xl">🦊</span>
                <div className="flex-1 text-left">
                  <p className="font-semibold text-white text-sm">{wallet.isConnecting ? 'Connecting…' : 'MetaMask'}</p>
                  <p className="text-xs" style={{ color: '#475569' }}>Browser extension wallet</p>
                </div>
                {wallet.isConnecting
                  ? <div className="w-4 h-4 rounded-full border-2 border-white/20 border-t-white/80 animate-spin" />
                  : <span style={{ color: '#f97316' }}>→</span>}
              </button>

              <button disabled className="w-full flex items-center gap-4 py-4 px-5 rounded-2xl opacity-30 cursor-not-allowed"
                style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                <span className="text-2xl">🔗</span>
                <div className="flex-1 text-left">
                  <p className="font-semibold text-sm flex items-center gap-2" style={{ color: '#94a3b8' }}>
                    WalletConnect
                    <span className="text-xs px-1.5 py-0.5 rounded-full" style={{ background: 'rgba(139,92,246,0.15)', color: '#a78bfa' }}>v2</span>
                  </p>
                  <p className="text-xs" style={{ color: '#1e293b' }}>Coming soon</p>
                </div>
              </button>

              <button disabled className="w-full flex items-center gap-4 py-4 px-5 rounded-2xl opacity-30 cursor-not-allowed"
                style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                <span className="text-2xl">🔵</span>
                <div className="flex-1 text-left">
                  <p className="font-semibold text-sm" style={{ color: '#94a3b8' }}>Coinbase Wallet</p>
                  <p className="text-xs" style={{ color: '#1e293b' }}>Coming soon</p>
                </div>
              </button>
            </div>

            <div className="mt-5 pt-4" style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
              <p className="text-center text-xs" style={{ color: '#1e293b' }}>Mainnet · Goerli · Sepolia</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
