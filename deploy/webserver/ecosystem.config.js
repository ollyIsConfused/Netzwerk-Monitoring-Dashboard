// pm2 ecosystem file fuer Backend + Frontend auf dem Webserver.
// Start (von beliebigem Verzeichnis aus):  pm2 start deploy/webserver/ecosystem.config.js
// Vorher: backend/.venv anlegen und Requirements installieren, Repo-Root/.env
//         befuellen (siehe .env.example) und Frontend einmalig bauen (npm run build)
//         - siehe docs/deployment.md fuer die vollstaendige Anleitung.
const path = require("path");

module.exports = {
  apps: [
    {
      name: "monitoring-backend",
      cwd: __dirname,
      script: "./run-backend.sh",
      interpreter: "bash",
      autorestart: true,
    },
    {
      name: "monitoring-frontend",
      cwd: path.join(__dirname, "..", "..", "frontend"),
      script: "npx",
      args: "serve -s dist -l 5173",
      autorestart: true,
    },
  ],
};
