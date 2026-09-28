
import React from 'react';
import ReactDOM from 'react-dom/client';
import './styles/index.css';
import App from './app/App';
import { AppErrorBoundary } from './app/AppErrorBoundary';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AppErrorBoundary><App /></AppErrorBoundary>
  </React.StrictMode>,
);
