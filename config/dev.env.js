'use strict'
const { merge } = require('webpack-merge')
const prodEnv = require('./prod.env')
require('dotenv').config()

module.exports = merge(prodEnv, {
  NODE_ENV: '"development"',
  VUE_APP_CESIUM_TOKEN: JSON.stringify(process.env.VUE_APP_CESIUM_TOKEN || '')
})
