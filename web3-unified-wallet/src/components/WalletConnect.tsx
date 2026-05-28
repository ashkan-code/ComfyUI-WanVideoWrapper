import { WalletState, WalletActions } from '../hooks/useWallet'

interface Props {
  wallet: WalletState & WalletActions
}

export function WalletConnect({ wallet }: Props) {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-slate-900 p-6">
      {/* Background grid */}
      <div
        className="absolute inset-0 opacity-5"
        style={{
          backgroundImage:
            'linear-gradient(#6366f1 1px, transparent 1px), linear-gradient(to right, #6366f1 1px, transparent 1px)',
          backgroundSize: '40px 40px',
        }}
      />

      <div className="relative bg-slate-800/80 backdrop-blur-sm rounded-2xl p-8 max-w-sm w-full shadow-2xl border border-slate-700/50">
        {/* Logo */}
        <div className="flex justify-center mb-6">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <span className="text-3xl">⟠</span>
          </div>
        </div>

        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-white mb-1">Web3 Unified Wallet</h1>
          <p className="text-slate-400 text-sm">Connect your wallet to continue</p>
        </div>

        {wallet.error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-300 rounded-xl p-3 mb-4 text-sm flex items-start gap-2">
            <span className="mt-0.5 shrink-0">⚠</span>
            <span>{wallet.error}</span>
          </div>
        )}

        <div className="space-y-3">
          {/* MetaMask */}
          <button
            onClick={wallet.connect}
            disabled={wallet.isConnecting}
            className="w-full group flex items-center gap-4 bg-slate-700/50 hover:bg-orange-500/10 border border-slate-600/50 hover:border-orange-500/40 disabled:opacity-50 disabled:cursor-not-allowed text-white py-3.5 px-4 rounded-xl transition-all duration-200"
          >
            <span className="text-2xl">🦊</span>
            <div className="flex-1 text-left">
              <p className="font-semibold text-sm">
                {wallet.isConnecting ? 'Connecting…' : 'MetaMask'}
              </p>
              <p className="text-slate-400 text-xs">Browser extension wallet</p>
            </div>
            {wallet.isConnecting ? (
              <div className="w-4 h-4 border-2 border-white/20 border-t-white rounded-full animate-spin" />
            ) : (
              <span className="text-slate-500 group-hover:text-slate-300 transition-colors">→</span>
            )}
          </button>

          {/* WalletConnect */}
          <button
            disabled
            className="w-full flex items-center gap-4 bg-slate-700/30 border border-slate-600/30 text-slate-500 py-3.5 px-4 rounded-xl cursor-not-allowed"
          >
            <span className="text-2xl opacity-50">🔗</span>
            <div className="flex-1 text-left">
              <p className="font-semibold text-sm flex items-center gap-2">
                WalletConnect
                <span className="text-xs bg-indigo-500/20 text-indigo-400 px-2 py-0.5 rounded-full font-normal">
                  v2 Ready
                </span>
              </p>
              <p className="text-slate-600 text-xs">Mobile & desktop wallets</p>
            </div>
          </button>

          {/* Coinbase Wallet */}
          <button
            disabled
            className="w-full flex items-center gap-4 bg-slate-700/30 border border-slate-600/30 text-slate-500 py-3.5 px-4 rounded-xl cursor-not-allowed"
          >
            <span className="text-2xl opacity-50">🔵</span>
            <div className="flex-1 text-left">
              <p className="font-semibold text-sm flex items-center gap-2">
                Coinbase Wallet
                <span className="text-xs bg-slate-600/50 text-slate-500 px-2 py-0.5 rounded-full font-normal">
                  Coming Soon
                </span>
              </p>
              <p className="text-slate-600 text-xs">Self-custody crypto wallet</p>
            </div>
          </button>
        </div>

        <p className="text-center text-slate-600 text-xs mt-6">
          Supports Ethereum Mainnet · Goerli · Sepolia
        </p>
      </div>

      {window.electronAPI?.isElectron && (
        <p className="relative mt-4 text-slate-600 text-xs">
          Running as Electron desktop app · Platform: {window.electronAPI.platform}
        </p>
      )}
    </div>
  )
}
