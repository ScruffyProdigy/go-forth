import { config } from './config.js';
import { createApp } from './app.js';

createApp().listen(config.apiPort, () => {
  console.log(`Go Forth! api listening on http://localhost:${config.apiPort}`);
});
