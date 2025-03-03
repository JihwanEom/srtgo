from datetime import datetime, timedelta
from json.decoder import JSONDecodeError
from random import gammavariate
from requests.exceptions import ConnectionError
from termcolor import colored
from typing import Awaitable, Callable, List, Optional, Tuple, Union

import asyncio
import click
import inquirer
import keyring
import telegram
import time
import re

from .ktx import (
    Korail,
    KorailError,
    ReserveOption,
    TrainType,
    AdultPassenger,
    ChildPassenger,
    SeniorPassenger,
    Disability1To3Passenger,
    Disability4To6Passenger
)

from .srt import (
    SRT,
    SRTError,
    SeatType,
    Adult,
    Child,
    Senior,
    Disability1To3,
    Disability4To6
)


STATIONS = {
    "SRT": [
        "수서", "동탄", "평택지제", "경주", "곡성", "공주", "광주송정", "구례구", "김천(구미)",
        "나주", "남원", "대전", "동대구", "마산", "목포", "밀양", "부산", "서대구",
        "순천", "여수EXPO", "여천", "오송", "울산(통도사)", "익산", "전주",
        "정읍", "진영", "진주", "창원", "창원중앙", "천안아산", "포항"
    ],
    "KTX": [
        "서울", "용산", "영등포", "광명", "수원", "천안아산", "오송", "대전", "서대전",
        "김천구미", "동대구", "경주", "포항", "밀양", "구포", "부산", "울산(통도사)",
        "마산", "창원중앙", "경산", "논산", "익산", "정읍", "광주송정", "목포",
        "전주", "순천", "여수EXPO", "청량리", "강릉", "행신", "정동진"
    ]
}

# --- 변경된 부분 ---
# 출발역/도착역을 각각 따로 기본값으로 갖게끔 수정
DEFAULT_STATIONS = {
    "SRT": {
        "departure": ["수서"],
        "arrival": ["동대구"]
    },
    "KTX": {
        "departure": ["서울"],
        "arrival": ["부산"]
    }
}
# --- 여기까지 ---

# 예약 간격 (평균 간격 (초) = SHAPE * SCALE)
RESERVE_INTERVAL_SHAPE = 4
RESERVE_INTERVAL_SCALE = 0.25
RESERVE_INTERVAL_MIN = 0.5

WAITING_BAR = ["|", "/", "-", "\\"]

RailType = Union[str, None]
ChoiceType = Union[int, None]


@click.command()
@click.option("--debug", is_flag=True, help="Debug mode")
def srtgo(debug=False):
    MENU_CHOICES = [
        ("예매 시작", 1),
        ("예매 확인/취소", 2),
        ("로그인 설정", 3),
        ("텔레그램 설정", 4),
        ("카드 설정", 5),
        ("역 설정", 6),
        ("역 직접 수정", 7),
        ("예매 옵션 설정", 8),
        ("나가기", -1)
    ]

    RAIL_CHOICES = [
        (colored("SRT", "red"), "SRT"),
        (colored("KTX", "cyan"), "KTX"),
        ("취소", -1)
    ]

    ACTIONS = {
        1: lambda rt: reserve(rt, debug),
        2: lambda rt: check_reservation(rt, debug),
        3: lambda rt: set_login(rt, debug),
        4: lambda _: set_telegram(),
        5: lambda _: set_card(),
        # --- 변경된 부분 ---
        6: lambda rt: set_station(rt),   # 출발역/도착역 분리 설정
        7: lambda rt: edit_station(rt),  # 출발역/도착역 분리 직접 입력
        # --- 여기까지 ---
        8: lambda _: set_options()
    }

    while True:
        choice = inquirer.list_input(message="메뉴 선택 (↕:이동, Enter: 선택)", choices=MENU_CHOICES)

        if choice == -1:
            break

        if choice in {1, 2, 3, 6, 7}:
            rail_type = inquirer.list_input(
                message="열차 선택 (↕:이동, Enter: 선택, Ctrl-C: 취소)",
                choices=RAIL_CHOICES
            )
            if rail_type in {-1, None}:
                continue
        else:
            rail_type = None

        action = ACTIONS.get(choice)
        if action:
            action(rail_type)


# --- 변경된 부분 ---
def set_station(rail_type: RailType) -> bool:
    """
    출발역과 도착역을 각각 선택형(Checkbox)으로 나눠서 설정한다.
    선택된 값들은 keyring에 "departure_stations", "arrival_stations" 키로 저장된다.
    """
    if rail_type not in STATIONS:
        print("유효하지 않은 열차 유형입니다.")
        return False

    # 전체 역 목록 (SRT or KTX)
    all_stations = STATIONS[rail_type]
    # 이미 저장되어 있으면 불러오고, 없으면 기본값 사용
    current_departure = (keyring.get_password(rail_type, "departure_stations") or "")
    current_arrival = (keyring.get_password(rail_type, "arrival_stations") or "")

    # 문자열 -> 리스트
    if current_departure.strip():
        dep_list = [s.strip() for s in current_departure.split(',')]
    else:
        dep_list = DEFAULT_STATIONS[rail_type]["departure"]

    if current_arrival.strip():
        arr_list = [s.strip() for s in current_arrival.split(',')]
    else:
        arr_list = DEFAULT_STATIONS[rail_type]["arrival"]

    # 출발역 체크박스
    dep_answer = inquirer.prompt([
        inquirer.Checkbox(
            "dep_stations",
            message="(출발역) 역 선택 (↕:이동, Space: 선택, Enter: 완료, Ctrl-A: 전체선택, Ctrl-R: 선택해제)",
            choices=all_stations,
            default=dep_list
        )
    ])
    if not dep_answer or not dep_answer.get("dep_stations"):
        print("출발역이 선택되지 않았습니다.")
        return False

    # 도착역 체크박스
    arr_answer = inquirer.prompt([
        inquirer.Checkbox(
            "arr_stations",
            message="(도착역) 역 선택 (↕:이동, Space: 선택, Enter: 완료, Ctrl-A: 전체선택, Ctrl-R: 선택해제)",
            choices=all_stations,
            default=arr_list
        )
    ])
    if not arr_answer or not arr_answer.get("arr_stations"):
        print("도착역이 선택되지 않았습니다.")
        return False

    selected_dep = ','.join(dep_answer["dep_stations"])
    selected_arr = ','.join(arr_answer["arr_stations"])

    keyring.set_password(rail_type, "departure_stations", selected_dep)
    keyring.set_password(rail_type, "arrival_stations", selected_arr)

    print(f"[{rail_type}] 설정된 출발역: {selected_dep}")
    print(f"[{rail_type}] 설정된 도착역: {selected_arr}")
    return True


def edit_station(rail_type: RailType) -> bool:
    """
    출발역과 도착역을 각각 직접 입력받아서 설정한다.
    예: '수서,대전,동탄' 식으로 콤마 구분
    """
    if rail_type not in STATIONS:
        print("유효하지 않은 열차 유형입니다.")
        return False

    current_departure = (keyring.get_password(rail_type, "departure_stations") or "")
    current_arrival = (keyring.get_password(rail_type, "arrival_stations") or "")

    station_info = inquirer.prompt([
        inquirer.Text(
            "dep_stations",
            message="(출발역) 직접 수정 (예: 수서,대전,동탄)",
            default=current_departure
        ),
        inquirer.Text(
            "arr_stations",
            message="(도착역) 직접 수정 (예: 동대구,부산,광주송정)",
            default=current_arrival
        )
    ])

    if not station_info:
        return False

    dep_input = station_info.get("dep_stations", "").strip()
    arr_input = station_info.get("arr_stations", "").strip()

    if not dep_input:
        print("출발역이 입력되지 않았습니다.")
        return False
    if not arr_input:
        print("도착역이 입력되지 않았습니다.")
        return False

    # 콤마 구분 -> 리스트
    dep_list = [s.strip() for s in dep_input.split(',')]
    arr_list = [s.strip() for s in arr_input.split(',')]

    # 간단하게 한글 역명인지 확인
    hangul = re.compile('[가-힣]+')

    for station in dep_list:
        if not hangul.search(station):
            print(f"'{station}'(출발역)은 잘못된 입력입니다. 기본 설정으로 복귀합니다.")
            dep_list = DEFAULT_STATIONS[rail_type]["departure"]
            break

    for station in arr_list:
        if not hangul.search(station):
            print(f"'{station}'(도착역)은 잘못된 입력입니다. 기본 설정으로 복귀합니다.")
            arr_list = DEFAULT_STATIONS[rail_type]["arrival"]
            break

    # 다시 콤마 문자열로 합쳐서 저장
    selected_dep = ','.join(dep_list)
    selected_arr = ','.join(arr_list)

    keyring.set_password(rail_type, "departure_stations", selected_dep)
    keyring.set_password(rail_type, "arrival_stations", selected_arr)

    print(f"[{rail_type}] 설정된 출발역: {selected_dep}")
    print(f"[{rail_type}] 설정된 도착역: {selected_arr}")
    return True
# --- 여기까지 수정 ---

def get_options():
    options = keyring.get_password("SRT", "options") or ""
    return options.split(',') if options else []

def set_options():
    default_options = get_options()
    choices = inquirer.prompt([
        inquirer.Checkbox(
            "options",
            message="예매 옵션 선택 (Space: 선택, Enter: 완료, Ctrl-A: 전체선택, Ctrl-R: 선택해제, Ctrl-C: 취소)",
            choices=[
                ("어린이", "child"),
                ("경로우대", "senior"),
                ("중증장애인", "disability1to3"),
                ("경증장애인", "disability4to6"),
                ("KTX만", "ktx")
            ],
            default=default_options
        )
    ])

    if choices is None:
        return

    options = choices.get("options", [])
    keyring.set_password("SRT", "options", ','.join(options))

def set_telegram() -> bool:
    token = keyring.get_password("telegram", "token") or ""
    chat_id = keyring.get_password("telegram", "chat_id") or ""

    telegram_info = inquirer.prompt([
        inquirer.Text("token", message="텔레그램 token (Enter: 완료, Ctrl-C: 취소)", default=token),
        inquirer.Text("chat_id", message="텔레그램 chat_id (Enter: 완료, Ctrl-C: 취소)", default=chat_id)
    ])
    if not telegram_info:
        return False

    token, chat_id = telegram_info["token"], telegram_info["chat_id"]

    try:
        keyring.set_password("telegram", "ok", "1")
        keyring.set_password("telegram", "token", token)
        keyring.set_password("telegram", "chat_id", chat_id)
        tgprintf = get_telegram()
        asyncio.run(tgprintf("[SRTGO] 텔레그램 설정 완료"))
        return True
    except Exception as err:
        print(err)
        keyring.delete_password("telegram", "ok")
        return False

def get_telegram() -> Optional[Callable[[str], Awaitable[None]]]:
    token = keyring.get_password("telegram", "token")
    chat_id = keyring.get_password("telegram", "chat_id")

    async def tgprintf(text):
        if token and chat_id:
            bot = telegram.Bot(token=token)
            async with bot:
                await bot.send_message(chat_id=chat_id, text=text)

    return tgprintf

def set_card() -> None:
    """
    카드 정보를 입력받아 keyring 에 저장한다.
    - inquirer.Text를 사용해 입력 시 마스킹되지 않도록 함
    - 유효기간은 MMYY 형태로 입력받는다(예: '0527')
    """
    card_info = {
        "number": keyring.get_password("card", "number") or "",
        "password": keyring.get_password("card", "password") or "",
        "birthday": keyring.get_password("card", "birthday") or "",
        "expire": keyring.get_password("card", "expire") or ""
    }

    card_info = inquirer.prompt([
        inquirer.Text(
            "number",
            message="신용카드 번호 (하이픈 제외(-), Enter: 완료, Ctrl-C: 취소)",
            default=card_info["number"]
        ),
        inquirer.Text(
            "password",
            message="카드 비밀번호 앞 2자리 (Enter: 완료, Ctrl-C: 취소)",
            default=card_info["password"]
        ),
        inquirer.Text(
            "birthday",
            message="생년월일 (YYMMDD) / 사업자등록번호 (Enter: 완료, Ctrl-C: 취소)",
            default=card_info["birthday"]
        ),
        # --- 여기에서 MMYY 형태로 입력받도록 메시지 수정 ---
        inquirer.Text(
            "expire",
            message="카드 유효기간 (MMYY 형식, 27년 05월 → '0527')",
            default=card_info["expire"]
        )
    ])
    if card_info:
        for key, value in card_info.items():
            keyring.set_password("card", key, value)
        keyring.set_password("card", "ok", "1")


def pay_card(rail, reservation) -> bool:
    """
    카드 정보를 이용해 결제한다.
    1. keyring에는 유효기간이 'MMYY' 형태로 저장되어 있음
    2. pay_with_card()는 'YYMM' 형태를 요구한다 가정
    3. 따라서 여기서 'MMYY'를 'YYMM'으로 변환 후 전달
    """
    if keyring.get_password("card", "ok"):
        birthday = keyring.get_password("card", "birthday")
        mm_yy = keyring.get_password("card", "expire") or ""

        # 'MMYY' → 'YYMM' 변환
        # 예: '0527'이면 month='05', year='27' → '27' + '05' = '2705'
        if len(mm_yy) == 4:
            yy_mm = mm_yy[2:] + mm_yy[:2]  # 앞뒤 슬라이스 재배치
        else:
            # 형식이 잘못된 경우 그대로 사용하거나, 따로 예외 처리 가능
            yy_mm = mm_yy

        return rail.pay_with_card(
            reservation,
            keyring.get_password("card", "number"),
            keyring.get_password("card", "password"),
            birthday,
            yy_mm,  # pay_with_card()가 YYMM을 요구한다고 가정
            0,
            "J" if len(birthday) == 6 else "S"
        )
    return False


def set_login(rail_type="SRT", debug=False):
    credentials = {
        "id": keyring.get_password(rail_type, "id") or "",
        "pass": keyring.get_password(rail_type, "pass") or ""
    }

    login_info = inquirer.prompt([
        inquirer.Text("id", message=f"{rail_type} 계정 아이디 (멤버십번호 OR 이메일 OR 전화번호, 전화번호는 하이픈 포함)", default=credentials["id"]),
        inquirer.Password("pass", message=f"{rail_type} 계정 패스워드", default=credentials["pass"])
    ])
    if not login_info:
        return False

    try:
        if rail_type == "SRT":
            SRT(login_info["id"], login_info["pass"], verbose=debug)
        else:
            Korail(login_info["id"], login_info["pass"], verbose=debug)

        keyring.set_password(rail_type, "id", login_info["id"])
        keyring.set_password(rail_type, "pass", login_info["pass"])
        keyring.set_password(rail_type, "ok", "1")
        return True
    except SRTError as err:
        print(err)
        keyring.delete_password(rail_type, "ok")
        return False

def login(rail_type="SRT", debug=False):
    if keyring.get_password(rail_type, "id") is None or keyring.get_password(rail_type, "pass") is None:
        set_login(rail_type)

    user_id = keyring.get_password(rail_type, "id")
    password = keyring.get_password(rail_type, "pass")

    if rail_type == "SRT":
        return SRT(user_id, password, verbose=debug)
    else:
        return Korail(user_id, password, verbose=debug)

def reserve(rail_type="SRT", debug=False):
    rail = login(rail_type, debug=debug)
    is_srt = (rail_type == "SRT")

    now = datetime.now() + timedelta(minutes=10)
    today = now.strftime("%Y%m%d")
    this_time = now.strftime("%H%M%S")

    # 기본값
    defaults = {
        "date": keyring.get_password(rail_type, "date") or today,
        "time": keyring.get_password(rail_type, "time") or "120000",
        "adult": int(keyring.get_password(rail_type, "adult") or 1),
        "child": int(keyring.get_password(rail_type, "child") or 0),
        "senior": int(keyring.get_password(rail_type, "senior") or 0),
        "disability1to3": int(keyring.get_password(rail_type, "disability1to3") or 0),
        "disability4to6": int(keyring.get_password(rail_type, "disability4to6") or 0)
    }

    # --- 변경된 부분 ---
    # 출발역/도착역을 불러올 때 각각 따로 로드
    saved_dep = keyring.get_password(rail_type, "departure_stations") or ""
    saved_arr = keyring.get_password(rail_type, "arrival_stations") or ""

    if saved_dep.strip():
        dep_list = [s.strip() for s in saved_dep.split(',')]
    else:
        dep_list = DEFAULT_STATIONS[rail_type]["departure"]

    if saved_arr.strip():
        arr_list = [s.strip() for s in saved_arr.split(',')]
    else:
        arr_list = DEFAULT_STATIONS[rail_type]["arrival"]

    # 출발역/도착역 기본 선택값이 없으면 첫 번째 값 사용
    defaults["departure"] = keyring.get_password(rail_type, "departure") or (dep_list[0] if dep_list else "")
    defaults["arrival"] = keyring.get_password(rail_type, "arrival") or (arr_list[0] if arr_list else "")
    # --- 여기까지 ---

    # 출발역과 도착역이 같으면 기본값 보정
    if defaults["departure"] == defaults["arrival"]:
        if is_srt:
            defaults["departure"], defaults["arrival"] = "수서", "동대구"
        else:
            defaults["departure"], defaults["arrival"] = "서울", "동대구"

    options = get_options()

    # 날짜/시간 선택지
    date_choices = [
        ((now + timedelta(days=i)).strftime("%Y/%m/%d %a"),
         (now + timedelta(days=i)).strftime("%Y%m%d")) for i in range(28)
    ]
    time_choices = [
        (f"{h:02d}", f"{h:02d}0000") for h in range(24)
    ]

    # 예약에 필요한 질문 구성
    q_info = [
        # 여기서 dep_list, arr_list를 사용하여 출발/도착역 선택
        inquirer.List("departure", message="출발역 선택 (↕:이동, Enter: 선택)",
                      choices=dep_list, default=defaults["departure"]),
        inquirer.List("arrival", message="도착역 선택 (↕:이동, Enter: 선택)",
                      choices=arr_list, default=defaults["arrival"]),
        inquirer.List("date", message="출발 날짜 선택 (↕:이동, Enter: 선택)",
                      choices=date_choices, default=defaults["date"]),
        inquirer.List("time", message="출발 시각 선택 (↕:이동, Enter: 선택)",
                      choices=time_choices, default=defaults["time"]),
        inquirer.List("adult", message="성인 승객수 (↕:이동, Enter: 선택)",
                      choices=range(10), default=defaults["adult"]),
    ]

    # 추가 승객 옵션
    passenger_types = {
        "child": "어린이",
        "senior": "경로우대",
        "disability1to3": "1~3급 장애인",
        "disability4to6": "4~6급 장애인"
    }
    passenger_classes = {
        "adult": Adult if is_srt else AdultPassenger,
        "child": Child if is_srt else ChildPassenger,
        "senior": Senior if is_srt else SeniorPassenger,
        "disability1to3": Disability1To3 if is_srt else Disability1To3Passenger,
        "disability4to6": Disability4To6 if is_srt else Disability4To6Passenger
    }

    for key, label in passenger_types.items():
        if key in options:  # 옵션 활성화된 타입만 물어봄
            q_info.append(inquirer.List(
                key,
                message=f"{label} 승객수 (↕:이동, Enter: 선택)",
                choices=range(10),
                default=defaults[key]
            ))

    info = inquirer.prompt(q_info)
    if not info:
        print(colored("예매 정보 입력 중 취소되었습니다", "green", "on_red") + "\n")
        return

    # 만약 사용자가 예매 과정에서 도착역 바꾸고 싶어도 여기서 고정해도 된다고 가정
    # (원 코드를 최대한 유지)
    if info["departure"] == info["arrival"]:
        print(colored("출발역과 도착역이 같습니다", "green", "on_red") + "\n")
        return

    # 사용자 입력값을 keyring에 저장(다음에 기본으로 불러올 수 있음)
    for key, value in info.items():
        keyring.set_password(rail_type, key, str(value))

    # 출발 날짜/시간 체크
    if info["date"] == today and int(info["time"]) < int(this_time):
        info["time"] = this_time

    # 승객 객체 생성
    passengers = []
    total_count = 0

    # 어른/청소년부터(기본)
    adult_count = info["adult"] if isinstance(info["adult"], int) else int(info["adult"])
    if adult_count > 0:
        passengers.append(passenger_classes["adult"](adult_count))
        total_count += adult_count

    # 추가 승객(어린이/경로/장애인)
    for k in ["child", "senior", "disability1to3", "disability4to6"]:
        if k in info and info[k] > 0:
            count = info[k] if isinstance(info[k], int) else int(info[k])
            if count > 0:
                passengers.append(passenger_classes[k](count))
                total_count += count

    if total_count == 0:
        print(colored("승객수는 0이 될 수 없습니다", "green", "on_red") + "\n")
        return
    if total_count >= 10:
        print(colored("승객수는 10명을 초과할 수 없습니다", "green", "on_red") + "\n")
        return

    # 검색 파라미터
    params = {
        "dep": info["departure"],
        "arr": info["arrival"],
        "date": info["date"],
        "time": info["time"],
        "passengers": passengers if is_srt else [AdultPassenger(total_count)],  # KTX는 일단 기본 AdultPassenger
    }

    # SRT/KTX별로 다르게 예약 검색
    if is_srt:
        params["available_only"] = False
    else:
        params["include_no_seats"] = True
        # 옵션에서 "ktx"가 있을 경우 KTX만 검색
        if "ktx" in options:
            params["train_type"] = TrainType.KTX

    trains = rail.search_train(**params)

    def train_decorator(train):
        msg = train.__repr__()
        return (msg.replace('예약가능', colored('가능', "green"))
                .replace('가능', colored('가능', "green"))
                .replace('신청하기', colored('가능', "green")))

    if not trains:
        print(colored("예약 가능한 열차가 없습니다", "green", "on_red") + "\n")
        return

    q_choice = [
        inquirer.Checkbox(
            "trains",
            message="예약할 열차 선택 (↕:이동, Space: 선택, Enter: 완료, Ctrl-A: 전체선택, Ctrl-R: 선택해제)",
            choices=[(train_decorator(train), i) for i, train in enumerate(trains)]
        )
    ]

    choice = inquirer.prompt(q_choice)
    if choice is None or not choice["trains"]:
        print(colored("선택한 열차가 없습니다!", "green", "on_red") + "\n")
        return

    seat_type = SeatType if is_srt else ReserveOption
    q_options = [
        inquirer.List("type", message="선택 유형",
                      choices=[
                          ("일반실 우선", seat_type.GENERAL_FIRST),
                          ("일반실만", seat_type.GENERAL_ONLY),
                          ("특실 우선", seat_type.SPECIAL_FIRST),
                          ("특실만", seat_type.SPECIAL_ONLY),
                      ]),
        inquirer.Confirm("pay", message="예매 시 카드 결제", default=False)
    ]

    options_ans = inquirer.prompt(q_options)
    if options_ans is None:
        print(colored("예매 정보 입력 중 취소되었습니다", "green", "on_red") + "\n")
        return

    def _reserve(train):
        reserve_ret = rail.reserve(train, passengers=passengers, option=options_ans["type"])
        msg = ""
        if is_srt:
            msg = (f"{reserve_ret}\n" + "\n".join(str(ticket) for ticket in reserve_ret.tickets))
        else:
            msg = str(reserve_ret).strip()

        print(colored(f"\n\n🎫 🎉 예매 성공!!! 🎉 🎫\n{msg}\n", "red", "on_green"))

        if options_ans["pay"] and hasattr(reserve_ret, "is_waiting") and not reserve_ret.is_waiting:
            # 카드 결제 시도
            if pay_card(rail, reserve_ret):
                print(colored("\n\n💳 ✨ 결제 성공!!! ✨ 💳\n\n", "green", "on_red"), end="")
                msg += "\n결제 완료"

        tgprintf = get_telegram()
        asyncio.run(tgprintf(msg))

    i_try = 0
    start_time = time.time()
    while True:
        try:
            i_try += 1
            elapsed_time = time.time() - start_time
            hours, remainder = divmod(int(elapsed_time), 3600)
            minutes, seconds = divmod(remainder, 60)
            print(
                f"\r예매 대기 중... {WAITING_BAR[i_try & 3]} {i_try:4d} "
                f"({hours:02d}:{minutes:02d}:{seconds:02d}) ",
                end="", flush=True
            )
            trains = rail.search_train(**params)
            for i in choice["trains"]:
                if _is_seat_available(trains[i], options_ans["type"], rail_type):
                    _reserve(trains[i])
                    return
            _sleep()

        except SRTError as ex:
            msg = ex.msg
            if "정상적인 경로로 접근 부탁드립니다" in msg:
                if debug:
                    print(f"\nException: {ex}\nType: {type(ex)}\nArgs: {ex.args}\nMessage: {msg}")
                rail.clear()
            elif "로그인 후 사용하십시오" in msg:
                if debug:
                    print(f"\nException: {ex}\nType: {type(ex)}\nArgs: {ex.args}\nMessage: {msg}")
                rail = login(rail_type, debug=debug)
                if not rail.is_login and not _handle_error(ex):
                    return
            elif not any(err in msg for err in (
                "잔여석없음", "사용자가 많아 접속이 원활하지 않습니다",
                "예약대기 접수가 마감되었습니다", "예약대기자한도수초과"
            )):
                if not _handle_error(ex):
                    return
            _sleep()

        except KorailError as ex:
            if not any(msg in str(ex) for msg in ("Sold out", "잔여석없음", "예약대기자한도수초과")):
                if not _handle_error(ex):
                    return
            _sleep()

        except JSONDecodeError as ex:
            if debug:
                print(f"\nException: {ex}\nType: {type(ex)}\nArgs: {ex.args}\nMessage: {ex.msg}")
            _sleep()
            rail = login(rail_type, debug=debug)

        except ConnectionError as ex:
            if not _handle_error(ex, "연결이 끊겼습니다"):
                return
            rail = login(rail_type, debug=debug)

        except Exception as ex:
            if debug:
                print("\nUndefined exception")
            if not _handle_error(ex):
                return
            rail = login(rail_type, debug=debug)

def _sleep():
    time.sleep(gammavariate(RESERVE_INTERVAL_SHAPE, RESERVE_INTERVAL_SCALE) + RESERVE_INTERVAL_MIN)

def _handle_error(ex, msg=None):
    msg = msg or f"\nException: {ex}, Type: {type(ex)}, Message: {ex.args}"
    print(msg)
    tgprintf = get_telegram()
    asyncio.run(tgprintf(msg))
    return inquirer.confirm(message="계속할까요", default=True)

def _is_seat_available(train, seat_type, rail_type):
    if rail_type == "SRT":
        if not train.seat_available():
            return train.reserve_standby_available()
        if seat_type in [SeatType.GENERAL_FIRST, SeatType.SPECIAL_FIRST]:
            return train.seat_available()
        if seat_type == SeatType.GENERAL_ONLY:
            return train.general_seat_available()
        return train.special_seat_available()
    else:
        if not train.has_seat():
            return train.has_waiting_list()
        if seat_type in [ReserveOption.GENERAL_FIRST, ReserveOption.SPECIAL_FIRST]:
            return train.has_seat()
        if seat_type == ReserveOption.GENERAL_ONLY:
            return train.has_general_seat()
        return train.has_special_seat()

def check_reservation(rail_type="SRT", debug=False):
    rail = login(rail_type, debug=debug)

    while True:
        if rail_type == "SRT":
            reservations = rail.get_reservations()
            tickets = []
        else:
            reservations = rail.reservations()
            tickets = rail.tickets()

        all_reservations = []
        for t in tickets:
            t.is_ticket = True
            all_reservations.append(t)
        for r in reservations:
            if hasattr(r, "paid") and r.paid:
                r.is_ticket = True
            else:
                r.is_ticket = False
            all_reservations.append(r)

        if not reservations and not tickets:
            print(colored("예약 내역이 없습니다", "green", "on_red") + "\n")
            return

        cancel_choices = [
            (str(reservation), i) for i, reservation in enumerate(all_reservations)
        ] + [("텔레그램으로 예매 정보 전송", -2), ("돌아가기", -1)]

        cancel = inquirer.list_input(
            message="예약 취소 (Enter: 결정)",
            choices=cancel_choices
        )

        if cancel in (None, -1):
            return

        if cancel == -2:
            out = []
            if all_reservations:
                out.append("[ 예매 내역 ]")
                for reservation in all_reservations:
                    out.append(f"🚅{reservation}")
                    if rail_type == "SRT":
                        out.extend(map(str, reservation.tickets))

            if out:
                tgprintf = get_telegram()
                asyncio.run(tgprintf("\n".join(out)))
            return

        if inquirer.confirm(message=colored("정말 취소하시겠습니까", "green", "on_red")):
            try:
                if all_reservations[cancel].is_ticket:
                    rail.refund(all_reservations[cancel])
                else:
                    rail.cancel(all_reservations[cancel])
            except Exception as err:
                raise err
            return


if __name__ == "__main__":
    srtgo()
