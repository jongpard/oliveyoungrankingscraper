#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# OliveYoung 카테고리별 랭킹 수집 (ScrapingAnt 422/403 우회 패치 적용 버전)

import os
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
import pandas as pd
from urllib.parse import quote_plus

# 로그 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# GitHub Actions Secret 또는 환경변수에서 ScrapingAnt API 키 로드
SCRAPINGANT_API_KEY = os.environ.get("SCRAPER_API_KEY", "").strip()

# 올리브영 카테고리 URL 맵 (원본 코드 데이터 유지)
category_url_map = {
    "전체": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_전체",
    "스킨케어": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000010001&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_스킨케어",
    "마스크팩": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000010009&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_마스크팩",
    "클렌징": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000010010&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_클렌징",
    "선케어": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000010011&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_선케어",
    "메이크업": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000010002&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_메이크업",
    "네일": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000010012&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_네일",
    "뷰티소품": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000010006&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_뷰티소품",
    "더모 코스메틱": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000010008&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_더모+코스메틱",
    "맨즈케어": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000010007&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_맨즈케어",
    "향수/디퓨저": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000010005&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_향수%2F디퓨저",
    "헤어케어": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000010004&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_헤어케어",
    "바디케어": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000010003&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_바디케어",
    "건강식품": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000020001&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_건강식품",
    "푸드": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000020002&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_푸드",
    "구강용품": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000020003&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_구강용품",
    "헬스/건강용품": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000020005&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_헬스%2F건강용품",
    "위생용품": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000020004&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_위생용품",
    "패션": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000030007&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_패션",
    "리빙/가전": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000030005&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_리빙%2F가전",
    "취미/팬시": "https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=10000030006&pageIdx=1&rowsPerPage=8&t_page=랭킹&t_click=판매랭킹_취미%2F팬시",
}

ordered_categories = [{'name': name, 'url': url} for name, url in category_url_map.items()]

def scrape_category_products_via_ant(category_name, category_url):
    """ScrapingAnt를 활용하여 특정 카테고리의 100개 상품 정보를 수집합니다."""
    logging.info(f"--- 카테고리 스크랩 중: {category_name} ---")
    
    if not SCRAPINGANT_API_KEY:
        logging.error("SCRAPER_API_KEY 환경변수가 비어있어 ScrapingAnt를 호출할 수 없습니다.")
        return []

    # 올리브영의 기본 rowsPerPage 파라미터는 8로 지정되어 있으므로, 100개 데이터 확보를 위해 변환합니다.
    target_url = category_url.replace("rowsPerPage=8", "rowsPerPage=100")
    
    try:
        # [교정 1] 422 에러 저격: 명시적 URL 인코딩 적용
        encoded_url = quote_plus(target_url)
        
        # [교정 2] 403 에러 저격: 파라미터 이름을 api_key 대신 x-api-key로 변경
        # browser=true 옵션을 주어 렌더링을 완전히 마친 완전한 HTML을 확보합니다.
        full_api_url = f"https://api.scrapingant.com/v2/general?x-api-key={SCRAPINGANT_API_KEY}&url={encoded_url}&browser=true"
        
        logging.info(f"ScrapingAnt 요청 전송 중... (Target: {category_name})")
        response = requests.get(full_api_url, timeout=60)
        logging.info(f"ScrapingAnt 응답 코드: {response.status_code}")
        
        if response.status_code != 200:
            logging.error(f"ScrapingAnt 호출 실패 (상태 코드: {response.status_code})")
            return []
            
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        
        # 원본 코드 선택자 매핑 (.cate_prd_list > li)
        product_elements = soup.select('.cate_prd_list > li')
        logging.info(f"파싱된 상품 요소 개수: {len(product_elements)}개")
        
        category_products_data = []
        for i, el in enumerate(product_elements):
            if i >= 100:
                break
                
            product_info = {'Category': category_name}
            
            # 1. 상품 URL 추출
            try:
                url_el = el.select_one('.prd_thumb') or el.select_one('a')
                href = url_el.get('href', '') if url_el else ''
                if href and href.startswith('/'):
                    href = "https://www.oliveyoung.co.kr" + href
                product_info['Product URL'] = href
            except Exception:
                product_info['Product URL'] = None

            # 2. 브랜드명 추출
            try:
                brand_el = el.select_one('.tx_brand')
                product_info['Brand'] = brand_el.get_text(strip=True) if brand_el else None
            except Exception:
                product_info['Brand'] = None

            # 3. 제품명 추출
            try:
                name_el = el.select_one('.tx_name')
                product_info['Product Name'] = name_el.get_text(strip=True) if name_el else None
            except Exception:
                product_info['Product Name'] = None

            # 4. 원래 가격 추출
            try:
                org_price_el = el.select_one('.tx_org .tx_num')
                product_info['Original Price'] = org_price_el.get_text(strip=True) + '원' if org_price_el else None
            except Exception:
                product_info['Original Price'] = None

            # 5. 할인가 추출
            try:
                sale_price_el = el.select_one('.tx_cur .tx_num')
                product_info['Sale Price'] = sale_price_el.get_text(strip=True) + '원' if sale_price_el else None
            except Exception:
                product_info['Sale Price'] = None

            # 6. 깃발/태그 추출
            try:
                flag_elements = el.select('.prd_flag .icon_flag')
                product_info['Flags'] = [f.get_text(strip=True) for f in flag_elements]
            except Exception:
                product_info['Flags'] = []

            # 7. 평점 추출
            try:
                rating_el = el.select_one('.review_point .point')
                if rating_el:
                    rating_text = rating_el.get_text(strip=True)
                    product_info['Rating'] = rating_text.replace('10점만점에 ', '')
                else:
                    product_info['Rating'] = None
            except Exception:
                product_info['Rating'] = None

            category_products_data.append(product_info)
            
            # 원본 화면 출력 로그 스타일 유지
            print("-" * 30)
            print(f"[{category_name} - {i+1}위]")
            if product_info.get('Brand'): print(f"  브랜드: {product_info['Brand']}")
            if product_info.get('Product Name'): print(f"  제품명: {product_info['Product Name']}")
            if product_info.get('Sale Price'): print(f"  가격: {product_info['Sale Price']}")
            elif product_info.get('Original Price'): print(f"  가격: {product_info['Original Price']}")
            if product_info.get('Rating'): print(f"  평점: {product_info['Rating']}")
            if product_info.get('Flags'): print(f"  태그: {', '.join(product_info['Flags'])}")
            
        logging.info(f"'{category_name}' 카테고리 수집 완료: 총 {len(category_products_data)}개")
        return category_products_data

    except Exception as e:
        logging.error(f"'{category_name}' 크롤링 중 에러 발생: {e}")
        return []

# --- 자동 수집 실행 파이프라인 ---
if __name__ == "__main__":
    print("✨ 올리브영 자동화 랭킹 스크래퍼 구동 (ScrapingAnt 엔진) ✨")
    
    all_scraped_data = []
    
    # GitHub Actions 환경이므로 사용자 입력 대기(while 루프)를 제거하고
    # 모든 카테고리를 순차적으로 자동 수집하도록 제어 구조를 자동화 전용으로 리팩토링합니다.
    for category in ordered_categories:
        cat_name = category['name']
        cat_url = category['url']
        
        products = scrape_category_products_via_ant(cat_name, cat_url)
        if products:
            all_scraped_data.extend(products)
        
        # 연속 차단 방지 및 API 크레딧 안전 버퍼용 지연 시간 설정
        time.sleep(3)

    # 누적 수집된 원본 파일 결과 빌드 및 출력 생성
    if all_scraped_data:
        df = pd.DataFrame(all_scraped_data)
        
        csv_filename = "oliveyoung_selected_products.csv"
        df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
        print(f"\n✅ 데이터 덤프 완료! CSV 저장 완료: '{csv_filename}'")

        excel_filename = "oliveyoung_selected_products.xlsx"
        df.to_excel(excel_filename, index=False)
        print(f"✅ 데이터 덤프 완료! Excel 저장 완료: '{excel_filename}'")
    else:
        print("\n⚠️ 수집된 랭킹 상품 정보가 전혀 존재하지 않습니다. API 키 및 권한을 확인하세요.")
