'use strict'
module.exports = {
  NODE_ENV: '"production"',
  VUE_APP_CESIUM_TOKEN: JSON.stringify(process.env.VUE_APP_CESIUM_TOKEN || ''),
  VUE_APP_GROQ_API_KEY: JSON.stringify(process.env.VUE_APP_GROQ_API_KEY || '')
}
