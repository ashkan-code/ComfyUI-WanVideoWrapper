# Web3 Unified Wallet

A production-ready Web3 wallet dashboard built with **Electron + React + ethers.js v6**, demonstrating MetaMask integration, transaction workflows, and smart contract interaction.

Built as a portfolio piece to showcase Electron + Web3 architecture for the [TechHavenLabs Web3 Developer](https://cryptojobs.com) role.

---

## Features

| Feature | Details |
|---|---|
| **Wallet Connection** | MetaMask via `ethers.BrowserProvider` · WalletConnect v2 interface ready · Coinbase Wallet interface ready |
| **Dashboard** | Live ETH balance · Copy address · Network name with per-chain color badge |
| **Network Switcher** | Ethereum Mainnet · Goerli · Sepolia — one-click switch via `wallet_switchEthereumChain` |
| **Send ETH** | Address validation · real-time gas estimation (EIP-1559 + legacy) · transaction submission · status tracking |
| **Transaction Monitor** | Pending/Confirmed/Failed badges · live status via `tx.wait()` · Etherscan deep links |
| **ERC-20 Reader** | Read any ERC-20 token balance · Quick presets: USDC, USDT, LINK · `ethers.Contract` multicall |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Desktop Shell | Electron 28 |
| Frontend | React 18 + TypeScript 5 (strict mode) |
| Blockchain | ethers.js v6 (`BrowserProvider`, `Contract`, `TransactionResponse`) |
| Build | Vite 5 |
| Styling | Tailwind CSS v3 (dark theme) |

---

## Architecture

```
electron/
├── main.ts      — BrowserWindow + setWindowOpenHandler (routes external links to system browser)
└── preload.ts   — contextBridge: exposes platform info; never exposes Node.js APIs

src/
├── types/
│   └── global.d.ts         — window.ethereum EthereumProvider interface
├── lib/
│   └── ethers.ts           — BrowserProvider factory, network configs, ERC-20 ABI, formatters
├── hooks/
│   ├── useWallet.ts        — wallet state machine: connect / disconnect / switchNetwork / refreshBalance
│   └── useTransactions.ts  — transaction list: addTransaction / updateTransaction / clearTransactions
└── components/
    ├── WalletConnect.tsx   — connect screen: MetaMask + WalletConnect + Coinbase buttons
    ├── Dashboard.tsx       — balance card + network switcher + address copy
    ├── SendEth.tsx         — form with gas estimation preview and tx submission
    ├── TransactionList.tsx — history with live status badges and Etherscan links
    └── ContractReader.tsx  — ERC-20 balance reader with preset contracts
```

---

## Setup

### Prerequisites

- Node.js 18+
- MetaMask browser extension (for wallet connection)

### Install

```bash
cd web3-unified-wallet
npm install
```

### Run — Browser mode (full MetaMask support)

```bash
npm run dev
# Opens at http://localhost:5173
# MetaMask injects window.ethereum automatically
```

### Run — Electron desktop app

```bash
npm run dev:electron
# Starts Vite + Electron concurrently
# Electron waits for Vite to be ready, then loads the renderer
```

### Build

```bash
npm run build          # Compile Electron TS + Vite renderer build
npm run typecheck      # TypeScript check (renderer, strict)
npm run typecheck:electron  # TypeScript check (Electron main/preload)
```

---

## Key Implementation Details

### ethers.js v6 — Wallet Connection

```typescript
// Request account access via MetaMask
const provider = new ethers.BrowserProvider(window.ethereum)
const accounts = await provider.send('eth_requestAccounts', []) as string[]
const signer   = await provider.getSigner()

// Get balance (returns bigint in ethers v6)
const balance = await provider.getBalance(accounts[0])
console.log(ethers.formatEther(balance))  // "1.2345"
```

### Gas Estimation — EIP-1559 + Legacy Support

```typescript
const feeData  = await provider.getFeeData()
const gasLimit = await provider.estimateGas({ from: signer.address, to, value })

// Support both EIP-1559 (maxFeePerGas) and legacy (gasPrice) networks
const gasPrice = feeData.maxFeePerGas ?? feeData.gasPrice ?? 0n
const gasCost  = gasLimit * gasPrice  // all bigint arithmetic — no precision loss
```

### Transaction Lifecycle

```typescript
const tx      = await signer.sendTransaction({ to, value: ethers.parseEther(amount) })
// hash available immediately — add to history as 'pending'

const receipt = await tx.wait(1)
// null if replaced; receipt.status === 1 → confirmed, 0 → reverted
const status  = receipt === null ? 'failed' : receipt.status === 1 ? 'confirmed' : 'failed'
```

### ERC-20 Contract Read

```typescript
const contract = new ethers.Contract(contractAddress, ERC20_ABI, provider)

const [balance, decimals, symbol] = await Promise.all([
  contract.balanceOf(address) as Promise<bigint>,
  contract.decimals()         as Promise<bigint>,
  contract.symbol()           as Promise<string>,
])

const formatted = ethers.formatUnits(balance, Number(decimals))
```

### Electron Security

```typescript
// main.ts — BrowserWindow config
webPreferences: {
  contextIsolation: true,   // renderer cannot access Node.js APIs
  nodeIntegration: false,   // standard Electron security practice
  preload: path.join(__dirname, 'preload.js'),
}

// External links (Etherscan) → system browser, not in-app
win.webContents.setWindowOpenHandler(({ url }) => {
  shell.openExternal(url)
  return { action: 'deny' }
})
```

---

## Extending

**WalletConnect v2**
Replace the placeholder button with `@walletconnect/modal` initialization and pass the resulting provider to `new ethers.BrowserProvider(wcProvider)`:
```typescript
import { createWeb3Modal, defaultWagmiConfig } from '@web3modal/wagmi'
// ... configure and pass provider to useWallet
```

**Multi-chain ERC-20 (e.g., Polygon, Arbitrum)**
Add chain entries to `NETWORKS` in `src/lib/ethers.ts` and configure `wallet_addEthereumChain` for unknown chains in `switchNetwork`.

**Persistent transaction history**
Replace `useState` in `useTransactions.ts` with `localStorage` via `useLocalStorage` — the hook interface stays identical.
