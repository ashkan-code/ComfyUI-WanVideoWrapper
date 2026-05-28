import { useState, useEffect, useCallback } from 'react'
import { ethers } from 'ethers'
import { getProvider, NETWORKS, formatEth } from '../lib/ethers'

export interface WalletState {
  address: string | null
  balance: string | null
  chainId: number | null
  networkName: string
  isConnected: boolean
  isConnecting: boolean
  error: string | null
  provider: ethers.BrowserProvider | null
}

export interface WalletActions {
  connect: () => Promise<void>
  disconnect: () => void
  switchNetwork: (chainId: number) => Promise<void>
  refreshBalance: () => Promise<void>
}

const INITIAL_STATE: WalletState = {
  address: null,
  balance: null,
  chainId: null,
  networkName: '',
  isConnected: false,
  isConnecting: false,
  error: null,
  provider: null,
}

export function useWallet(): WalletState & WalletActions {
  const [state, setState] = useState<WalletState>(INITIAL_STATE)

  const refreshBalance = useCallback(async () => {
    if (!state.provider || !state.address) return
    try {
      const raw = await state.provider.getBalance(state.address)
      setState(prev => ({ ...prev, balance: formatEth(raw) }))
    } catch {
      // non-critical
    }
  }, [state.provider, state.address])

  const connect = useCallback(async () => {
    if (!window.ethereum) {
      setState(prev => ({
        ...prev,
        error: 'MetaMask is not installed. Please install it from metamask.io',
      }))
      return
    }

    setState(prev => ({ ...prev, isConnecting: true, error: null }))

    try {
      const provider = getProvider()!
      const accounts = (await provider.send('eth_requestAccounts', [])) as string[]

      if (!accounts.length) throw new Error('No accounts returned from MetaMask')

      const address = accounts[0]
      const network = await provider.getNetwork()
      const chainId = Number(network.chainId)
      const rawBalance = await provider.getBalance(address)

      setState({
        address,
        balance: formatEth(rawBalance),
        chainId,
        networkName: NETWORKS[chainId]?.name ?? `Chain ${chainId}`,
        isConnected: true,
        isConnecting: false,
        error: null,
        provider,
      })
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message.includes('rejected')
            ? 'Connection rejected by user'
            : err.message
          : 'Failed to connect wallet'
      setState(prev => ({ ...prev, isConnecting: false, error: message }))
    }
  }, [])

  const disconnect = useCallback(() => {
    setState(INITIAL_STATE)
  }, [])

  const switchNetwork = useCallback(async (targetChainId: number) => {
    if (!window.ethereum) return
    setState(prev => ({ ...prev, error: null }))
    try {
      await window.ethereum.request({
        method: 'wallet_switchEthereumChain',
        params: [{ chainId: `0x${targetChainId.toString(16)}` }],
      })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to switch network'
      setState(prev => ({ ...prev, error: message }))
    }
  }, [])

  // MetaMask event listeners
  useEffect(() => {
    if (!window.ethereum) return

    const handleAccountsChanged = (accounts: unknown) => {
      const accs = accounts as string[]
      if (accs.length === 0) {
        disconnect()
        return
      }
      const provider = getProvider()!
      setState(prev => ({ ...prev, address: accs[0], provider }))
      provider.getBalance(accs[0]).then(raw =>
        setState(prev => ({ ...prev, balance: formatEth(raw) }))
      ).catch(() => undefined)
    }

    const handleChainChanged = () => {
      // Reload is the safest approach — MetaMask recommends it
      window.location.reload()
    }

    window.ethereum.on('accountsChanged', handleAccountsChanged)
    window.ethereum.on('chainChanged', handleChainChanged)

    return () => {
      window.ethereum?.removeListener('accountsChanged', handleAccountsChanged)
      window.ethereum?.removeListener('chainChanged', handleChainChanged)
    }
  }, [disconnect])

  return { ...state, connect, disconnect, switchNetwork, refreshBalance }
}
