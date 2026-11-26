const express = require('express');
const healthRoutes = require('./health');
const importRoutes = require('./imports');
const questionRoutes = require('./questions');

const router = express.Router();

router.use('/health', healthRoutes);
router.use('/imports', importRoutes);
router.use('/questions', questionRoutes);

module.exports = router;