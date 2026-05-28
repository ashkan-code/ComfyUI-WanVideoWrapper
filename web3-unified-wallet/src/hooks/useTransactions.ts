import { useState, useCallback } from 'react'

export type TxStatus = 'pending' | 'confirmed' | 'failed'

export interface Transaction {
  hash: string
  to: string
  value: string
  status: TxStatus
  timestamp: number
  chainId: number
}

export interface TransactionActions {
  addTransaction: (tx: Omit<Transaction, 'timestamp' | 'status'>) => Transaction
  updateTransaction: (hash: string, status: TxStatus) => void
  clearTransactions: () => void
}

export function useTransactions(): { transactions: Transaction[] } & TransactionActions {
  const [transactions, setTransactions] = useState<Transaction[]>([])

  const addTransaction = useCallback(
    (tx: Omit<Transaction, 'timestamp' | 'status'>): Transaction => {
      const newTx: Transaction = { ...tx, status: 'pending', timestamp: Date.now() }
      setTransactions(prev => [newTx, ...prev])
      return newTx
    },
    []
  )

  const updateTransaction = useCallback((hash: string, status: TxStatus) => {
    setTransactions(prev =>
      prev.map(tx => (tx.hash === hash ? { ...tx, status } : tx))
    )
  }, [])

  const clearTransactions = useCallback(() => setTransactions([]), [])

  return { transactions, addTransaction, updateTransaction, clearTransactions }
}
