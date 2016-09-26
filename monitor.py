import asyncio
import time
import logging
import configparser
import os

import aiohttp
from aiohttp import web
from bs4 import BeautifulSoup


config = configparser.ConfigParser(delimiters=(" ",))
config.read("config.ini")
# Protection from being banned
MAX_CONNECTIONS = config["REQUESTS"].getint("MAX_SIMULTANIOUS_CONNECTIONS")
# Pause between request to each separate url
DURATION = config["REQUESTS"].getint("CHECKING_PERIOD")
# Configuration of one page HTTP server with results of scraping
IP = config["HTTP_SERVER"]["IP"]
PORT = config["HTTP_SERVER"]["PORT"]

# Get pairs (URL, text_to_find)
urls = [(url, config["URLS"][url][1:-1]) for url in config["URLS"]]

# get absolute path on general log file
log_file_path = os.path.join(os.path.dirname(
            os.path.abspath(__file__)),
            "ScrapingLog.log")

# Basic HTML template fot HTTP server (with automatic refresh)
html_report = "<html><head><meta http-equiv='refresh' content='1'></head><body> %s </body></html>"
# Variable part of HTML report (could be used stuff with redis here as variant)
html_records = []

# Initialization of semaphore to prevent too much of simultanious connections
# (from being banned)
semaphore = asyncio.Semaphore(MAX_CONNECTIONS)

# Get event loop to control asynchronous calls
loop = asyncio.get_event_loop()
# Init debug mode of event loop
loop.set_debug(enabled=True)


# Custom filter on all log messages appearing in event loop
# We are interested only in our custom messages
class CustomFilter(logging.Filter):
    def filter(self, record):
        keys = ["Host:", "New iteration started at:"]
        # Only messages about executed new request to url or info about new general iteration
        return any([key in record.getMessage() for key in keys])

# Logging configuration
logging.basicConfig(filename="ScrapingLog.log",
                    format="%(levelname)s: %(message)s",
                    level=logging.INFO)
logger = logging.getLogger("asyncio")
logger.addFilter(CustomFilter())

# Instance of web server with logging data
app = web.Application(loop=loop)

# Handler on our web server to precess requests
async def handle(request):
    global html_records
    text = html_report % "".join(html_records)
    return web.Response(text=text, content_type="text/html")

# Routing on 127.0.0.1:8000 by default
app.router.add_get('/', handle)
# Initialization of instance of our web server
server = loop.create_server(app.make_handler(), IP, PORT)


# Coroutine to process url requests
async def get_page_content(semaphore, client, url, text, log):
    # To change content of HTML log
    global html_records
    # Limitation on maximum of simultanious connections
    async with semaphore:
        # Wait before request to url
        await asyncio.sleep(DURATION)
        # Used for calculation of spended time
        start_time = time.time()
        try:
            # Init client instance by url passed
            async with client.get(url) as resp:
                # Init HTML parser by result of request
                soup = BeautifulSoup(await resp.text(), "html.parser")
                # Check presence of passed text in result of request
                match_found = True if soup.find(string=text) else False
                # Check how much time was spended
                elapsed_time = time.time() - start_time
                # If we have match in html of page
                if match_found:
                    # Then create INFO log message
                    log.info(
                        "Host: %s, connection code: %s, match result: match found, total time: %.4f sec." %
                        (url, resp.status, elapsed_time)
                    )
                    # And append list of all log messages for current iteration for html log
                    html_records.append(
                        "\n<BR>INFO: Host: %s, connection code: %s, match result: match found, total time: %.4f sec." %
                        (url, resp.status, elapsed_time)
                    )
                # No match was found
                else:
                    # Then create WARNING log message
                    log.warning(
                        "Host: %s, connection code: %s, match result: [>>>match not found<<<], total time: %.4f sec." %
                        (url, resp.status, elapsed_time)
                    )
                    # And append list of all log messages for current iteration for html log
                    html_records.append(
                        "\n<BR>WARNING: Host: %s, connection code: %s, match result: [>>>match not found<<<], total time: %.4f sec." %
                        (url, resp.status, elapsed_time)
                    )
        # If error occurred during requesting to url
        except aiohttp.errors.ClientConnectionError as e:
            # Calculate spended time
            elapsed_time = time.time() - start_time
            # Create ERROR message for log
            log.error(
                "Host: %s, [>>>connection error, code: %s<<<], time: %.4f sec." %
                (url, e.args[0], elapsed_time)
            )
            # And append list of all log messages for current iteration for html log
            html_records.append(
                "\n<BR>ERROR: Host: %s, [>>>connection error, code: %s<<<], time: %.4f sec." %
                (url, e.args[0], elapsed_time)
            )

# Starting point of script
with aiohttp.ClientSession(loop=loop) as client:
    # Start HTTP server
    loop.run_until_complete(server)
    while True:
        logger.info(
            "New iteration started at: %s" % time.strftime("%Y-%m-%d %H:%M:%S")
        )
        # New iteration started by all urls, left only this record in HTML log
        html_records = ["New iteration started at: %s" % time.strftime("%Y-%m-%d %H:%M:%S")]
        # Run loop by all urls from config file
        loop.run_until_complete(
            asyncio.wait(
                [get_page_content(semaphore, client, url, text, logger) for url, text in urls]
            )
        )
