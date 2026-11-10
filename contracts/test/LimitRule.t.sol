// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

import {AegisToken} from "../src/AegisToken.sol";
import {LimitRule} from "../src/rules/LimitRule.sol";
import {AegisTest} from "./AegisTest.sol";

/// 지시서의 "작은 토큰": 내 규칙(LimitRule)만 붙은 시험용 컨트랙트.
/// AegisToken 을 거치지 않아서, 세 규칙이 합쳐져도 다른 사람의 규칙에 막히지 않는다.
/// 결제 흐름 대신 _checkPayment 를 직접 부른다. 토큰에 제대로 연결됐는지는 아래 wiring 시험 2개가 따로 본다.
contract LimitOnly is LimitRule {
    constructor(address initialOwner) Ownable(initialOwner) {}

    function check(address from, address to, uint256 amount, bytes32 requestId) external {
        _checkPayment(from, to, amount, requestId);
    }
}

/// 시나리오 1: 한 건씩은 한도 안인 결제를 여러 번 보내 하루 상한을 넘기려는 공격을 막는지 시험한다.
/// 주의: expectRevert 바로 앞뒤에서 컨트랙트를 부르면(외부 호출) 그 호출이 먼저 걸리므로, 값은 미리 계산해 둔다.
contract LimitRuleTest is AegisTest {
    LimitOnly h;
    address owner = makeAddr("owner");
    address buyer;
    uint256 buyerKey;
    address buyer2;
    address seller = makeAddr("seller");
    uint256 seq;

    function setUp() public {
        (buyer, buyerKey) = makeAddrAndKey("buyer");
        buyer2 = makeAddr("buyer2");
        h = new LimitOnly(owner);
    }

    // 숫자는 규칙의 설정값에서 계산한다 (코드에 직접 쓰지 않는다).
    function _amount() internal view returns (uint256) {
        return (h.limitPerPayment() * 4) / 5; // 한 건 상한의 80%
    }

    function _passCount() internal view returns (uint256) {
        return h.limitPerDay() / _amount(); // 하루 상한 안에서 통과하는 건수
    }

    function _id() internal returns (bytes32) {
        return keccak256(abi.encode("limit-req", ++seq)); // 결제마다 다른 요청 번호
    }

    /// 하루 상한을 넘는 결제부터 막힌다. 막힌 결제는 합계를 늘리지 않는다.
    function test_dailyLimitBlocksFromTheNextPayment() public {
        uint256 amount = _amount();
        uint256 passCount = _passCount();

        for (uint256 i = 0; i < passCount; i++) {
            h.check(buyer, seller, amount, _id());
        }
        bytes32 id = _id();
        vm.expectRevert(abi.encodeWithSelector(LimitRule.OverDailyLimit.selector, buyer, passCount * amount, amount));
        h.check(buyer, seller, amount, id);

        assertEq(h.dailyUsed(buyer, block.timestamp / 1 days), passCount * amount);
    }

    /// 한 건 상한을 넘는 결제는 바로 막힌다.
    function test_perPaymentLimitBlocksImmediately() public {
        uint256 tooBig = h.limitPerPayment() + 1;
        bytes32 id = _id();

        vm.expectRevert(abi.encodeWithSelector(LimitRule.OverPaymentLimit.selector, tooBig));
        h.check(buyer, seller, tooBig, id);
        assertEq(h.dailyUsed(buyer, block.timestamp / 1 days), 0);
    }

    /// 경계: 한 건 상한과 정확히 같은 금액은 통과한다.
    function test_perPaymentLimitBoundaryIsInclusive() public {
        uint256 exact = h.limitPerPayment();
        h.check(buyer, seller, exact, _id());
        assertEq(h.dailyUsed(buyer, block.timestamp / 1 days), exact);
    }

    /// 경계: 합계가 하루 상한과 정확히 같으면 통과하고, 1 units 더 넘으면 막힌다.
    function test_dailyLimitBoundaryIsInclusive() public {
        uint256 limit = h.limitPerDay();
        uint256 perPayment = h.limitPerPayment();

        uint256 remaining = limit;
        while (remaining > 0) {
            uint256 chunk = remaining < perPayment ? remaining : perPayment;
            h.check(buyer, seller, chunk, _id());
            remaining -= chunk;
        }
        assertEq(h.dailyUsed(buyer, block.timestamp / 1 days), limit);

        bytes32 id = _id();
        vm.expectRevert(abi.encodeWithSelector(LimitRule.OverDailyLimit.selector, buyer, limit, 1));
        h.check(buyer, seller, 1, id);
    }

    /// 하루가 지나면 합계가 0부터 다시 시작한다.
    function test_limitResetsNextDay() public {
        uint256 amount = _amount();
        uint256 passCount = _passCount();

        for (uint256 i = 0; i < passCount; i++) {
            h.check(buyer, seller, amount, _id());
        }
        vm.warp(block.timestamp + 1 days);
        h.check(buyer, seller, amount, _id()); // 다음 날이라 통과
        assertEq(h.dailyUsed(buyer, block.timestamp / 1 days), amount);
    }

    /// 한도는 구매자 지갑(from)별로 센다. 모든 결제의 msg.sender 는 중개자 한 명이다.
    function test_limitIsPerWalletNotPerRelayer() public {
        uint256 amount = _amount();
        uint256 passCount = _passCount();

        for (uint256 i = 0; i < passCount; i++) {
            vm.prank(relayer); // 보내는 쪽은 늘 중개자
            h.check(buyer, seller, amount, _id());
        }
        vm.prank(relayer);
        h.check(buyer2, seller, amount, _id()); // 다른 지갑은 영향이 없다
        assertEq(h.dailyUsed(buyer2, block.timestamp / 1 days), amount);
    }

    /// 한도 값은 운영자(owner)만 바꿀 수 있다.
    function test_onlyOwnerChangesLimits() public {
        uint256 newLimit = h.limitPerDay() + 1;

        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, buyer));
        h.setLimitPerDay(newLimit);

        vm.prank(owner);
        h.setLimitPerDay(newLimit);
        assertEq(h.limitPerDay(), newLimit);
    }

    /// 한도를 낮추면 바로 적용된다.
    function test_loweredLimitTakesEffect() public {
        uint256 amount = _amount();
        h.check(buyer, seller, amount, _id()); // 지금은 통과

        vm.prank(owner);
        h.setLimitPerPayment(amount - 1);
        bytes32 id = _id();
        vm.expectRevert(abi.encodeWithSelector(LimitRule.OverPaymentLimit.selector, amount));
        h.check(buyer, seller, amount, id);
    }

    // ---- 진짜 토큰에 연결됐는지(wiring): 결제 한 건씩만 보내서 다른 규칙의 횟수 제한에 걸리지 않게 한다 ----

    /// 진짜 토큰으로 한도 안의 결제가 통과한다.
    function test_wiring_tokenPaymentWithinLimitPasses() public {
        AegisToken token = new AegisToken(owner);
        uint256 amount = (token.limitPerPayment() * 4) / 5;
        vm.prank(owner);
        token.mint(buyer, amount);

        _pay(token, buyerKey, seller, amount, _id());
        assertEq(token.balanceOf(seller), amount);
    }

    /// 진짜 토큰에서도 한 건 상한을 넘는 결제는 revert 된다.
    function test_wiring_tokenRejectsOverPaymentLimit() public {
        AegisToken token = new AegisToken(owner);
        uint256 tooBig = token.limitPerPayment() + 1;
        vm.prank(owner);
        token.mint(buyer, tooBig);
        bytes32 id = _id();

        vm.expectRevert(abi.encodeWithSelector(LimitRule.OverPaymentLimit.selector, tooBig));
        _pay(token, buyerKey, seller, tooBig, id);
    }
}