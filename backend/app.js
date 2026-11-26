const express = require('express');
const path = require('node:path');
const apiRoutes = require('./routes');

const app = express();
const frontendPath = path.join(__dirname, '..', 'frontend', 'public');

app.use(express.json({ limit: '12mb' }));
app.use('/api', apiRoutes);
app.use('/vendor', express.static(path.join(__dirname, '..', 'node_modules', 'exceljs', 'dist')));
app.get('/shared/importer.js', (request, response) => {
  response.sendFile(path.join(__dirname, '..', 'shared', 'importer.js'));
});
app.use(express.static(frontendPath));

module.exports = app;