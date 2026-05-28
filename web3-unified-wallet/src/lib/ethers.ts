import { ethers } from 'ethers'

export interface NetworkInfo {
  name: string
  explorer: string
  color: string
}

export const NETWORKS: Record<number, NetworkInfo> = {
  1:        { name: 'Ethereum Mainnet', explorer: 'https://etherscan.io',         color: '#627EEA' },
  5:        { name: 'Goerli Testnet',   explorer: 'https://goerli.etherscan.io',  color: '#F6C343' },
  11155111: { name: 'Sepolia Testnet',  explorer: 'https://sepolia.etherscan.io', color: '#CFB5F0' },
}

// USDC contract address on Ethereum mainnet
export const USDC_ADDRESS = '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'

export const ERC20_ABI = [
  'function balanceOf(address owner) view returns (uint256)',
  'function decimals() view returns (uint8)',
  'function symbol() view returns (string)',
  'function name() view returns (string)',
]

export function shortenAddress(address: string): string {
  return `${address.slice(0, 6)}…${address.slice(-4)}`
}

export function getExplorerTxUrl(chainId: number, txHash: string): string {
  const network = NETWORKS[chainId]
  const base = network?.explorer ?? 'https://etherscan.io'
  return `${base}/tx/${txHash}`
}

export function getExplorerAddressUrl(chainId: number, address: string): string {
  const network = NETWORKS[chainId]
  const base = network?.explorer ?? 'https://etherscan.io'
  return `${base}/address/${address}`
}

export function getProvider(): ethers.BrowserProvider | null {
  if (!window.ethereum) return null
  return new ethers.BrowserProvider(window.ethereum)
}

export function formatEth(value: bigint, precision = 4): string {
  return parseFloat(ethers.formatEther(value)).toFixed(precision)
}
