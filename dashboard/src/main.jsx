
import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import RedesignApp from './redesign/RedesignApp';
import { AppErrorBoundary } from './redesign/AppErrorBoundary';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AppErrorBoundary><RedesignApp /></AppErrorBoundary>
  </React.StrictMode>,
);
