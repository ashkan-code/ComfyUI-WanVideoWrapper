import { contextBridge } from 'electron'

// Expose only what the renderer needs — never expose Node.js APIs directly
contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,
  isElectron: true,
})
