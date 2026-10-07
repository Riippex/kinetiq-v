module.exports = ({ config }) => {
  if (process.env.KINETIQ_LOCAL_ANDROID_BUILD !== '1') return config;
  return {
    ...config,
    name: 'Kinetiq V Local',
    plugins: [...(config.plugins ?? []), './plugins/withLocalNetwork'],
  };
};
