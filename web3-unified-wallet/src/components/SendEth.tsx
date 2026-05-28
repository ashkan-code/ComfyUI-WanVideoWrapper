import { useState } from 'react'
import { ethers } from 'ethers'
import { WalletState } from '../hooks/useWallet'
import { Transaction } from '../hooks/useTransactions'
import { getExplorerTxUrl, shortenAddress } from '../lib/ethers'

interface Props {
  wallet: WalletState
  onTransactionSent: (tx: Omit<Transaction, 'timestamp' | 'status'>) => void
  onTransactionConfirmed: (hash: string, status: 'confirmed' | 'failed') => void
}

export function SendEth({ wallet, onTransactionSent, onTransactionConfirmed }: Props) {
  const [to, setTo]               = useState('')
  const [amount, setAmount]       = useState('')
  const [gasEth, setGasEth]       = useState<string | null>(null)
  const [isEstimating, setIsEstimating] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const [error, setError]         = useState<string | null>(null)
  const [sentHash, setSentHash]   = useState<string | null>(null)

  const isValidAddress = to.length > 0 && ethers.isAddress(to)
  const isValidAmount  = amount.length > 0 && parseFloat(amount) > 0

  const estimateGas = async () => {
    if (!wallet.provider || !isValidAddress || !isValidAmount) return
    setIsEstimating(true)
    setError(null)
    setGasEth(null)

    try {
      const signer   = await wallet.provider.getSigner()
      const value    = ethers.parseEther(amount)
      const feeData  = await wallet.provider.getFeeData()
      const gasLimit = await wallet.provider.estimateGas({ from: signer.address, to, value })

      // Support both legacy (gasPrice) and EIP-1559 (maxFeePerGas) networks
      const gasPrice = feeData.maxFeePerGas ?? feeData.gasPrice ?? 0n
      setGasEth(ethers.formatEther(gasLimit * gasPrice))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Gas estimation failed')
    } finally {
      setIsEstimating(false)
    }
  }

  const send = async () => {
    if (!wallet.provider || !isValidAddress || !isValidAmount) return
    setIsSending(true)
    setError(null)
    setSentHash(null)

    let pendingHash: string | null = null

    try {
      const signer = await wallet.provider.getSigner()
      const value  = ethers.parseEther(amount)
      const tx     = await signer.sendTransaction({ to, value })

      pendingHash = tx.hash
      setSentHash(tx.hash)
      onTransactionSent({ hash: tx.hash, to, value: amount, chainId: wallet.chainId ?? 1 })

      const receipt = await tx.wait()
      const status  = receipt?.status === 1 ? 'confirmed' : 'failed'
      onTransactionConfirmed(tx.hash, status)

      if (status === 'confirmed') {
        setTo('')
        setAmount('')
        setGasEth(null)
      } else {
        setError('Transaction was reverted on-chain')
      }
    } catch (err) {
      const message = err instanceof Error
        ? err.message.includes('rejected') ? 'Transaction rejected by user' : err.message
        : 'Transaction failed'
      setError(message)
      if (pendingHash) onTransactionConfirmed(pendingHash, 'failed')
    } finally {
      setIsSending(false)
    }
  }

  return (
    <div className="bg-slate-800/60 rounded-xl p-6 border border-slate-700/50">
      <h2 className="text-white font-semibold text-lg mb-5">Send ETH</h2>

      <div className="space-y-4">
        {/* Recipient */}
        <div>
          <label className="block text-slate-400 text-xs font-medium uppercase tracking-wider mb-1.5">
            Recipient Address
          </label>
          <div className="relative">
            <input
              type="text"
              value={to}
              onChange={e => { setTo(e.target.value); setGasEth(null) }}
              placeholder="0x…"
              spellCheck={false}
              className="w-full bg-slate-700/50 text-white rounded-xl px-4 py-3 text-sm font-mono border border-slate-600/50 focus:border-indigo-500 focus:outline-none transition-colors placeholder:text-slate-600"
            />
            {to.length > 0 && (
              <span className={`absolute right-3 top-1/2 -translate-y-1/2 text-xs font-medium ${
                isValidAddress ? 'text-green-400' : 'text-red-400'
              }`}>
                {isValidAddress ? '✓ Valid' : '✗ Invalid'}
              </span>
            )}
          </div>
        </div>

        {/* Amount */}
        <div>
          <label className="block text-slate-400 text-xs font-medium uppercase tracking-wider mb-1.5">
            Amount
          </label>
          <div className="relative">
            <input
              type="number"
              value={amount}
              onChange={e => { setAmount(e.target.value); setGasEth(null) }}
              placeholder="0.0"
              min="0"
              step="0.001"
              className="w-full bg-slate-700/50 text-white rounded-xl px-4 py-3 pr-16 text-sm border border-slate-600/50 focus:border-indigo-500 focus:outline-none transition-colors placeholder:text-slate-600"
            />
            <span className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 text-sm font-medium">
              ETH
            </span>
          </div>
          {wallet.balance && (
            <button
              onClick={() => setAmount(wallet.balance!)}
              className="mt-1 text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
            >
              Max: {wallet.balance} ETH
            </button>
          )}
        </div>

        {/* Gas Estimate */}
        {gasEth && (
          <div className="bg-slate-700/30 rounded-xl px-4 py-3 flex justify-between items-center border border-slate-600/30">
            <div className="flex items-center gap-2 text-slate-400 text-sm">
              <span>⛽</span>
              <span>Estimated gas fee</span>
            </div>
            <span className="text-white font-mono text-sm">
              ~{parseFloat(gasEth).toFixed(6)} ETH
            </span>
          </div>
        )}

        {/* Sent hash */}
        {sentHash && (
          <div className="bg-indigo-500/10 border border-indigo-500/30 rounded-xl px-4 py-3">
            <p className="text-indigo-300 text-xs font-medium mb-1">Transaction submitted</p>
            <a
              href={getExplorerTxUrl(wallet.chainId ?? 1, sentHash)}
              target="_blank"
              rel="noopener noreferrer"
              className="text-indigo-400 hover:text-indigo-300 font-mono text-xs transition-colors"
            >
              {shortenAddress(sentHash)} ↗
            </a>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-300 rounded-xl p-3 text-sm flex items-start gap-2">
            <span className="shrink-0 mt-0.5">⚠</span>
            <span>{error}</span>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3 pt-1">
          <button
            onClick={estimateGas}
            disabled={!isValidAddress || !isValidAmount || isEstimating || isSending}
            className="flex-1 bg-slate-700/50 hover:bg-slate-600/50 border border-slate-600/50 disabled:opacity-40 disabled:cursor-not-allowed text-slate-300 hover:text-white py-3 rounded-xl text-sm font-medium transition-all duration-200"
          >
            {isEstimating ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-3 h-3 border border-slate-400 border-t-transparent rounded-full animate-spin" />
                Estimating…
              </span>
            ) : '⛽ Estimate Gas'}
          </button>

          <button
            onClick={send}
            disabled={!isValidAddress || !isValidAmount || isSending || isEstimating}
            className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white py-3 rounded-xl text-sm font-semibold transition-all duration-200 shadow-lg shadow-indigo-500/10"
          >
            {isSending ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-3 h-3 border border-white/40 border-t-white rounded-full animate-spin" />
                Sending…
              </span>
            ) : '↗ Send ETH'}
          </button>
        </div>
      </div>
    </div>
  )
}
