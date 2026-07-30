import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './theme/blueprint-theme.css';
import App from './App.jsx';

// Default to dark mode before first paint (matches session store default)
document.body.classList.add('bp6-dark');

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
