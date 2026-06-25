import os
from dotenv import load_dotenv

load_dotenv()

from app import create_app

config_name = os.environ.get('FLASK_ENV', 'production')
if config_name == 'development':
    config_key = 'development'
else:
    config_key = 'production'

app = create_app(config_key)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=(config_key == 'development'))
