from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import pandas as pd
# from tabulate import tabulate # tabulate 모듈 주석 처리 또는 제거

# --- Chrome 옵션 설정 ---
chrome_options = Options()
# chrome_options.add_argument("--headless") # 주석을 해제하면 브라우저 창 없이 실행됩니다.
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev_shm_usage")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--window-size=1920,1080")

# --- ChromeDriver 경로 지정 ---
# 이곳을 사용자 환경에 맞게 수정하세요!
service = Service('/Users/baeminseo/Desktop/chromedriver/chromedriver')

# --- 올리브영 카테고리 URL 맵 ---
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

# category_url_map을 기반으로 순서가 보장된 카테고리 이름과 URL 리스트를 생성
ordered_categories = []
for name, url in category_url_map.items():
    ordered_categories.append({'name': name, 'url': url})

def scroll_to_bottom(driver):
    """페이지 하단으로 스크롤하여 모든 내용을 로드합니다."""
    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_attempts = 0
    max_scroll_attempts = 10 # 최대 스크롤 시도 횟수 제한 (무한 루프 방지)

    while scroll_attempts < max_scroll_attempts:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3) # 데이터 로드 대기 시간

        new_height = driver.execute_script("return document.body.scrollHeight")
        current_product_count = len(driver.find_elements(By.CSS_SELECTOR, '.cate_prd_list > li'))
        print(f"현재 로드된 상품 수: {current_product_count}개")

        if new_height == last_height and current_product_count >= 100:
            print("모든 100개 상품이 로드되었거나 더 이상 스크롤할 내용이 없습니다. 스크롤 종료.")
            break
        elif new_height == last_height:
            # 높이가 변하지 않는데 100개 미만이면, 추가 대기 후 다시 시도
            print(f"페이지 높이 변화 없음. 상품 수 {current_product_count}개. 추가 대기 후 재확인...")
            time.sleep(2) # 추가 대기
            current_product_count_after_wait = len(driver.find_elements(By.CSS_SELECTOR, '.cate_prd_list > li'))
            if current_product_count_after_wait == current_product_count:
                print(f"추가 대기 후에도 상품 수 변화 없음 ({current_product_count_after_wait}개). 스크롤 종료.")
                break # 더 이상 로드되지 않는다고 판단하고 종료
            else:
                current_product_count = current_product_count_after_wait # 상품이 더 로드되었다면 업데이트
        
        last_height = new_height
        scroll_attempts += 1 # 스크롤 시도 횟수 증가

    if scroll_attempts >= max_scroll_attempts:
        print(f"경고: 최대 스크롤 시도 횟수 ({max_scroll_attempts}회)에 도달했습니다. 모든 상품이 로드되지 않았을 수 있습니다.")


def scrape_category_products(driver, category_name, category_url):
    """주어진 카테고리에서 상품 정보를 스크랩하는 함수"""
    print(f"\n--- 카테고리 스크랩 중: {category_name} ---")
    driver.get(category_url)

    try:
        # 페이지가 완전히 로드될 때까지 기다립니다.
        # .cate_prd_list 요소가 존재하고, 그 안에 최소 1개의 li가 나타날 때까지 기다립니다.
        WebDriverWait(driver, 15).until( # 대기 시간 15초로 늘림
            EC.presence_of_element_located((By.CSS_SELECTOR, '.cate_prd_list > li'))
        )
        print("페이지 초기 요소 로드 완료.")
        time.sleep(2) # 초기 JS 렌더링을 위한 추가 대기 (넉넉하게)

        # --- 무한 스크롤 수행 ---
        print(f"'{category_name}' 카테고리 페이지 스크롤 중...")
        scroll_to_bottom(driver)
        print(f"'{category_name}' 카테고리 페이지 스크롤 완료.")
        time.sleep(3) # 스크롤 후 최종 데이터 로드를 위한 추가 대기 (넉넉하게)


        product_elements = driver.find_elements(By.CSS_SELECTOR, '.cate_prd_list > li')
        print(f"페이지에서 최종적으로 찾은 상품 요소 개수: {len(product_elements)}개")


        if not product_elements:
            print(f"오류: '{category_name}' 카테고리에서 상품 요소를 찾을 수 없습니다. HTML 구조 또는 선택자를 확인하세요.")
            return [] # 빈 리스트 반환

        category_products_data = []
        for i, product_element in enumerate(product_elements):
            product_info = {'Category': category_name}

            # 각 상품 요소 내부의 텍스트가 로드될 때까지 기다리는 강화된 로직
            try:
                # 브랜드 이름이 나타날 때까지 기다림
                WebDriverWait(product_element, 5).until( # 개별 요소당 5초 대기
                    EC.presence_of_element_located((By.CSS_SELECTOR, '.tx_brand'))
                )
            except Exception as e:
                print(f"경고: 상품 {i+1}번의 브랜드명 로딩 실패 - {e}. 다음 상품으로 이동.")
                continue # 이 상품은 건너뛰고 다음 상품으로

            # 상품 URL
            try:
                url_element = product_element.find_element(By.CSS_SELECTOR, '.prd_thumb')
                product_info['Product URL'] = url_element.get_attribute('href')
            except Exception as e:
                product_info['Product URL'] = None
                print(f"상품 {i+1}번 URL 추출 실패: {e}")

            # 브랜드명
            try:
                brand_element = product_element.find_element(By.CSS_SELECTOR, '.tx_brand')
                product_info['Brand'] = brand_element.text.strip()
            except Exception as e:
                product_info['Brand'] = None
                print(f"상품 {i+1}번 브랜드 추출 실패: {e}")

            # 제품명
            try:
                name_element = product_element.find_element(By.CSS_SELECTOR, '.tx_name')
                product_info['Product Name'] = name_element.text.strip()
            except Exception as e:
                product_info['Product Name'] = None
                print(f"상품 {i+1}번 제품명 추출 실패: {e}")

            # 원래 가격
            try:
                original_price_element = product_element.find_element(By.CSS_SELECTOR, '.tx_org .tx_num')
                product_info['Original Price'] = original_price_element.text.strip() + '원'
            except Exception as e:
                product_info['Original Price'] = None
                # print(f"상품 {i+1}번 원래 가격 추출 실패: {e}") # 모든 상품에 원가가 없을 수 있으니 경고는 생략

            # 할인가
            try:
                sale_price_element = product_element.find_element(By.CSS_SELECTOR, '.tx_cur .tx_num')
                product_info['Sale Price'] = sale_price_element.text.strip() + '원'
            except Exception as e:
                product_info['Sale Price'] = None
                print(f"상품 {i+1}번 할인가 추출 실패: {e}")

            # 깃발/태그
            flags = []
            try:
                flag_elements = product_element.find_elements(By.CSS_SELECTOR, '.prd_flag .icon_flag')
                for flag_el in flag_elements:
                    flags.append(flag_el.text.strip())
                product_info['Flags'] = flags
            except Exception as e:
                product_info['Flags'] = []
                # print(f"상품 {i+1}번 깃발 추출 실패: {e}")

            # 평점
            try:
                rating_element = product_element.find_element(By.CSS_SELECTOR, '.review_point .point')
                rating_text = rating_element.text.strip()
                if '10점만점에' in rating_text:
                    product_info['Rating'] = rating_text.replace('10점만점에 ', '')
                else:
                    product_info['Rating'] = rating_text
            except Exception as e:
                product_info['Rating'] = None
                # print(f"상품 {i+1}번 평점 추출 실패: {e}")

            category_products_data.append(product_info)
            
            # 여기서 각 상품 정보를 바로 출력합니다 (첫 번째 방식과 유사하게).
            print("-" * 30) # 구분선
            print(f"[{category_name} - {i+1}위]")
            if product_info.get('Brand'):
                print(f"  브랜드: {product_info['Brand']}")
            if product_info.get('Product Name'):
                print(f"  제품명: {product_info['Product Name']}")
            # 가격 출력 (할인가 우선, 없으면 원가)
            if product_info.get('Sale Price'):
                print(f"  가격: {product_info['Sale Price']}")
            elif product_info.get('Original Price'):
                print(f"  가격: {product_info['Original Price']}")
            
            if product_info.get('Rating'):
                print(f"  평점: {product_info['Rating']}")
            if product_info.get('Flags'):
                print(f"  태그: {', '.join(product_info['Flags'])}")
            if product_info.get('Product URL'):
                print(f"  링크: {product_info['Product URL']}")
            
        print(f"최종적으로 '{category_name}' 카테고리에서 {len(category_products_data)}개의 유효한 제품 정보를 추출했습니다.")
        return category_products_data

    except Exception as e:
        print(f"치명적 오류: '{category_name}' 카테고리 스크랩 중 초기 페이지 로드 실패: {e}")
        return []


# --- 메인 실행 로직 ---
if __name__ == "__main__":
    all_scraped_data = [] # 모든 스크랩 데이터를 저장할 리스트 (누적)
    
    # 웹 드라이버는 프로그램 시작 시 한 번만 초기화합니다.
    driver = None
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception as e:
        print(f"❌ 드라이버 초기화 중 오류 발생: {e}")
        print("ChromeDriver 경로를 확인하거나, Chrome 브라우저 및 ChromeDriver 버전이 일치하는지 확인해 주세요.")
        exit() # 드라이버 초기화 실패 시 프로그램 종료

    print("✨ 올리브영 랭킹 스크래퍼에 오신 것을 환영합니다! ✨")

    while True: # 카테고리 선택 및 스크래핑 반복 루프
        print("\n💚 원하는 카테고리별 인기 상품을 확인해보세요. 💚")

        # 가로 6칸, 세로 4줄 형태로 카테고리 출력 (매번 출력)
        num_columns = 6
        max_item_display_length = 0
        for i, category_item in enumerate(ordered_categories):
            display_str = f"{i+1:2}. {category_item['name']}"
            if len(display_str) > max_item_display_length:
                max_item_display_length = len(display_str)

        cell_width = max_item_display_length + 2

        print("-" * (cell_width * num_columns + (num_columns - 1) * 2))
        for i, category_item in enumerate(ordered_categories):
            category_name = category_item['name']
            formatted_item = f"{i+1:2}. {category_name}"
            
            print(f"{formatted_item:<{cell_width}}", end="")

            if (i + 1) % num_columns == 0:
                print()
            else:
                print("  ", end="")
        print()
        print("-" * (cell_width * num_columns + (num_columns - 1) * 2))

        selected_indices = []
        user_input_valid = False
        while not user_input_valid: # 유효한 입력을 받을 때까지 반복
            try:
                user_input = input("\n🔎 조회하고 싶은 카테고리 번호를 입력하세요 (여러 개는 쉼표로 구분, 'all'은 전체, '100'은 종료): ").strip()
                
                if user_input.lower() == '100':
                    print("👋 올리브영 랭킹 스크래퍼 작업을 완료하고 종료합니다. 👋")
                    print("✅ 수집된 데이터는 파일로 저장되었으니 확인해 주세요! 이용해주셔서 감사합니다. ✅")
                    driver.quit() # 프로그램 종료 시 드라이버 종료
                    exit() # 프로그램 종료
                elif user_input.lower() == 'all':
                    selected_indices = list(range(len(ordered_categories)))
                    user_input_valid = True
                else:
                    input_numbers = [int(x.strip()) for x in user_input.split(',') if x.strip().isdigit()]
                    if not input_numbers:
                        print("🚫 유효한 숫자 또는 'all', '100'을 입력해주세요.")
                        continue # 유효하지 않은 입력이므로 다시 입력 받음

                    valid_selection = True
                    temp_selected_indices = []
                    for num in input_numbers:
                        if 1 <= num <= len(ordered_categories):
                            temp_selected_indices.append(num - 1)
                        else:
                            print(f"⚠️ 경고: {num}은(는) 유효하지 않은 카테고리 번호입니다. 다시 선택해주세요.")
                            valid_selection = False
                            break
                    if valid_selection:
                        selected_indices = temp_selected_indices
                        user_input_valid = True
                    # else: continue는 이미 경고 출력 후 루프 처음으로 돌아감

            except ValueError:
                print("🚫 숫자 또는 'all', '100'을 올바른 형식으로 입력해주세요.")
            except Exception as e:
                print(f"❌ 입력 처리 중 오류 발생: {e}")
        
        # 선택된 카테고리 스크랩 시작
        current_scrape_data = [] # 현재 세션에서 스크랩된 데이터를 임시 저장
        try:
            for index in sorted(list(set(selected_indices))):
                category_item = ordered_categories[index]
                category_name = category_item['name']
                category_url = category_item['url']
                products = scrape_category_products(driver, category_name, category_url)
                if products: 
                    current_scrape_data.extend(products)
                    all_scraped_data.extend(products) # 전체 누적 데이터에도 추가
                else:
                    print(f"⚠️ 주의: '{category_name}' 카테고리에서 스크랩된 데이터가 없거나 추출에 실패했습니다. 이 카테고리는 결과에서 제외됩니다.")

            # 현재 세션에서 스크랩된 데이터 저장 및 안내
            if current_scrape_data:
                df = pd.DataFrame(all_scraped_data) # 누적된 전체 데이터를 기반으로 DataFrame 생성
                
                csv_filename = "oliveyoung_selected_products.csv"
                df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
                print(f"\n✅ 스크랩 완료! 모든 스크랩된 데이터가 '{csv_filename}'에 저장되었습니다.")

                excel_filename = "oliveyoung_selected_products.xlsx"
                df.to_excel(excel_filename, index=False)
                print(f"✅ 스크랩 완료! 모든 스크랩된 데이터가 '{excel_filename}'에 저장되었습니다.")
            else:
                print("\n⚠️ 이번 세션에서는 스크랩된 상품 정보가 없습니다.")
            
            print("\n🔄 더 궁금한 카테고리가 있으신가요? 카테고리 번호를 다시 입력해주세요.")
            # 루프는 계속되므로 자동으로 카테고리 선택 화면으로 돌아감

        except Exception as e:
            print(f"❌ 스크랩 과정 중 치명적인 오류 발생: {e}")
            # 이 오류는 드라이버 자체의 문제일 수 있으므로, 재시작을 고려하거나 종료하는 것이 좋습니다.
            # 여기서는 루프를 계속 돌도록 두지만, 실제 상황에서는 에러 로깅 후 종료를 고려할 수 있습니다.