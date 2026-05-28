/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      animation: {
        'spin-slow':   'spin 4s linear infinite',
        'ping-slow':   'ping 2s cubic-bezier(0,0,0.2,1) infinite',
        'float':       'float 3s ease-in-out infinite',
        'glow-pulse':  'glowPulse 2s ease-in-out infinite',
        'scan':        'scan 2s linear infinite',
        'slide-up':    'slideUp 0.4s ease-out',
        'fade-in':     'fadeIn 0.3s ease-out',
        'number-tick': 'numberTick 0.6s ease-out',
        'border-spin': 'borderSpin 3s linear infinite',
        'data-flow':   'dataFlow 8s linear infinite',
      },
      keyframes: {
        float:       { '0%,100%': { transform: 'translateY(0)' }, '50%': { transform: 'translateY(-8px)' } },
        glowPulse:   { '0%,100%': { opacity: '0.6' }, '50%': { opacity: '1' } },
        scan:        { '0%': { transform: 'translateY(-100%)' }, '100%': { transform: 'translateY(400%)' } },
        slideUp:     { '0%': { transform: 'translateY(16px)', opacity: '0' }, '100%': { transform: 'translateY(0)', opacity: '1' } },
        fadeIn:      { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        numberTick:  { '0%': { transform: 'translateY(8px)', opacity: '0' }, '100%': { transform: 'translateY(0)', opacity: '1' } },
        borderSpin:  { '0%': { '--angle': '0deg' }, '100%': { '--angle': '360deg' } },
        dataFlow:    { '0%': { backgroundPosition: '0% 0%' }, '100%': { backgroundPosition: '100% 100%' } },
      },
    },
  },
  plugins: [],
}
