# -*- coding: utf-8 -*-
import logging

from dateutil.relativedelta import relativedelta
from hdx.scraper.readers import read_hdx_metadata
from hdx.utilities.dictandlist import dict_of_lists_add
from hdx.utilities.downloader import Download
from hdx.utilities.text import number_format

logger = logging.getLogger(__name__)


def add_food_prices(configuration, today, countryiso3s, retriever, basic_auths, scrapers=None):
    name = 'food_prices'
    if scrapers and not any(scraper in name for scraper in scrapers):
        return list(), list(), list()
    datasetinfo = configuration[name]
    read_hdx_metadata(datasetinfo, today=today)
    base_url = datasetinfo['base_url']
    if retriever.use_saved:
        headers = None
    else:
        basic_auth = basic_auths[name]
        token_downloader = Download(basic_auth=basic_auth)
        token_downloader.download(f'{base_url}/token', post=True, parameters={'grant_type': 'client_credentials'})
        access_token = token_downloader.get_json()['access_token']
        headers = {'Accept': 'application/json', 'Authorization': f'Bearer {access_token}'}

    def get_list(endpoint, countryiso3, startdate=None):
        url = f'{base_url}/{endpoint}'
        filename = url.split('/')[-2]
        page = 1
        all_data = []
        data = None
        while data is None or len(data) > 0:
            parameters = {'CountryCode': countryiso3, 'page': page}
            if startdate:
                parameters['startDate'] = startdate
            try:
                json = retriever.retrieve_json(url, f'{filename}_{countryiso3}_{page}.json', f'{filename} for {countryiso3} page {page}', False,
                                               parameters=parameters, headers=headers)
            except FileNotFoundError:
                json = {'items': list()}
            data = json['items']
            all_data.extend(data)
            page = page + 1
        return all_data

    six_months_ago = today - relativedelta(months=6)
    ratios = dict()
    category_id_weights = {1: 2, 2: 4, 3: 4, 4: 1, 5: 3, 6: 0.5, 7: 0.5}
    for countryiso3 in countryiso3s:
        logger.info(f'Processing {countryiso3}')
        commodities = get_list('vam-data-bridges/1.1.0/Commodities/List', countryiso3)
        if not commodities:
            logger.info(f'{countryiso3} has no commodities!')
            continue
        commodity_id_to_category_id = {x['id']: x['categoryId'] for x in commodities}
        alps = get_list('vam-data-bridges/1.1.0/MarketPrices/Alps', countryiso3, six_months_ago)
        if not alps:
            logger.info(f'{countryiso3} has no ALPS!')
            continue
        yearmonth_rows = dict()
        for row in alps:
            analysis_value_price_flag = row['analysisValuePriceFlag']
            if analysis_value_price_flag == 'forecast':
                continue
            commodity_id = row['commodityID']
            category_id = commodity_id_to_category_id.get(commodity_id)
            if not category_id or category_id >= 8:
                continue
            row['categoryId'] = category_id
            yearmonth = f'{row["commodityPriceDateYear"]}/{row["commodityPriceDateMonth"]}'
            dict_of_lists_add(yearmonth_rows, yearmonth, row)
        yearmonths = yearmonth_rows.keys()
        if len(yearmonths) == 0:
            logger.info(f'{countryiso3} has no values!')
            continue
        latest_yearmonth = max(yearmonths)
        commodities_per_market = dict()
        commodities_per_market_crisis = dict()
        for row in yearmonth_rows[latest_yearmonth]:
            market_id = row['marketID']
            category_id = row['categoryId']
            weighted_value = category_id_weights[category_id]
            commodities_per_market[market_id] = commodities_per_market.get(market_id, 0) + weighted_value
            pewivalue = row['analysisValuePewiValue']
            if pewivalue >= 1.0:
                commodities_per_market_crisis[market_id] = commodities_per_market_crisis.get(market_id, 0) + weighted_value
        country_ratio = 0
        for market_id in commodities_per_market:
            market_ratio = commodities_per_market_crisis.get(market_id, 0) / commodities_per_market[market_id]
            country_ratio += market_ratio
        country_ratio /= len(commodities_per_market)
        ratios[countryiso3] = number_format(country_ratio, trailing_zeros=False)
    hxltag = '#value+food+num+ratio'
    logger.info('Processed WFP')
    return [['Food Prices Ratio'], [hxltag]], [ratios], [(hxltag, datasetinfo['date'], datasetinfo['source'], datasetinfo['source_url'])]
