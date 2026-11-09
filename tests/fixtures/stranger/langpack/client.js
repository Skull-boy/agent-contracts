const axios = require("axios");

async function status() {
  const response = await axios.get("https://example.com/status");
  return response.status;
}
